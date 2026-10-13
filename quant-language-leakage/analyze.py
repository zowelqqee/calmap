#!/usr/bin/env python3
"""Detect foreign-script intrusions in benchmark outputs and aggregate the statistics.

    python analyze.py --input results/raw.jsonl --output-dir results/analysis

Produces:
    <output-dir>/annotated.jsonl              every response + detector fields
    <output-dir>/by_quantization.csv          per quantization variant
    <output-dir>/by_quantization_category.csv per variant x prompt category
    <output-dir>/by_quantization_mode.csv     per variant x decoding mode
    <output-dir>/comparisons.csv              baseline vs each variant (Fisher exact)
    <output-dir>/report.md                    human readable summary
    results/intrusions.jsonl                  contaminated responses + context windows

Stdlib only: Wilson intervals, Fisher exact test and the Cochran-Armitage trend
test are implemented here so the analysis needs no numpy/scipy.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import sanity

# --------------------------------------------------------------------------
# Script ranges
# --------------------------------------------------------------------------

# Han. The first two ranges are the ones that matter in practice (URO + Ext A);
# the rest are included so an exotic codepoint is not silently missed.
HAN_RANGES = [
    (0x2E80, 0x2EFF),    # CJK Radicals Supplement
    (0x2F00, 0x2FDF),    # Kangxi Radicals
    (0x3005, 0x3005),    # ideographic iteration mark
    (0x3007, 0x3007),    # ideographic number zero
    (0x3021, 0x3029),    # Hangzhou numerals
    (0x3038, 0x303B),    # Hangzhou numerals / iteration marks
    (0x3400, 0x4DBF),    # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x20000, 0x2A6DF),  # Extension B
    (0x2A700, 0x2B73F),  # Extension C
    (0x2B740, 0x2B81F),  # Extension D
    (0x2B820, 0x2CEAF),  # Extension E
    (0x2CEB0, 0x2EBEF),  # Extension F
    (0x2EBF0, 0x2EE5F),  # Extension I
    (0x2F800, 0x2FA1F),  # Compatibility Ideographs Supplement
    (0x30000, 0x3134F),  # Extension G
    (0x31350, 0x323AF),  # Extension H
]

HIRAGANA_RANGES = [(0x3041, 0x309F), (0x1B001, 0x1B11F)]
KATAKANA_RANGES = [(0x30A0, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9D)]
HANGUL_RANGES = [
    (0x1100, 0x11FF),
    (0x3130, 0x318F),
    (0xA960, 0xA97F),
    (0xAC00, 0xD7A3),
    (0xD7B0, 0xD7FF),
    (0xFFA0, 0xFFDC),
]
# CJK punctuation / fullwidth forms: a weaker signal, tracked separately so it
# never inflates the Han intrusion rate.
CJK_PUNCT_RANGES = [(0x3000, 0x3004), (0x3008, 0x3020), (0x303C, 0x303F), (0xFF01, 0xFF65)]

# If a prompt legitimately asks about Chinese, a Han character is not leakage.
# The current benchmark contains no such prompts; the guard exists so the
# detector stays honest if prompts are extended later.
TOPIC_MARKERS = ("китайск", "иероглиф", "chinese", "mandarin", "hanzi", "kanji", "japanese", "korean")


def _in(ch: str, ranges) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ranges)


def detect(response: str, prompt: str = "") -> dict:
    """Return detector fields for one response."""
    han_positions, han_chars = [], []
    for i, ch in enumerate(response):
        if _in(ch, HAN_RANGES):
            han_positions.append(i)
            han_chars.append(ch)

    # contiguous Han runs -> the unit a human actually wants to look at
    segments = []
    for pos, ch in zip(han_positions, han_chars):
        if segments and pos == segments[-1]["end"]:
            segments[-1]["text"] += ch
            segments[-1]["end"] = pos + 1
        else:
            segments.append({"start": pos, "end": pos + 1, "text": ch})
    for seg in segments:
        lo = max(0, seg["start"] - 60)
        hi = min(len(response), seg["end"] + 60)
        seg["context"] = (
            response[lo:seg["start"]] + "⟦" + response[seg["start"]:seg["end"]] + "⟧" + response[seg["end"]:hi]
        ).replace("\n", " ")

    topical = any(m in (prompt + " " + response).lower() for m in TOPIC_MARKERS)

    return {
        "has_han": bool(han_chars),
        "han_char_count": len(han_chars),
        "han_chars": han_chars,
        "positions": han_positions,
        "han_segments": segments,
        "has_hiragana": any(_in(c, HIRAGANA_RANGES) for c in response),
        "has_katakana": any(_in(c, KATAKANA_RANGES) for c in response),
        "has_hangul": any(_in(c, HANGUL_RANGES) for c in response),
        "cjk_punct_count": sum(1 for c in response if _in(c, CJK_PUNCT_RANGES)),
        "topical_cjk_context": topical,
        "counts_as_leakage": bool(han_chars) and not topical,
        "response_chars": len(response),
    }


# --------------------------------------------------------------------------
# Statistics (stdlib only)
# --------------------------------------------------------------------------


def wilson(successes: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z / denom * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def _hypergeom_pmf(a: int, r1: int, r2: int, c1: int) -> float:
    n = r1 + r2
    return math.comb(r1, a) * math.comb(r2, c1 - a) / math.comb(n, c1)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for the 2x2 table [[a, b], [c, d]]."""
    r1, r2, c1 = a + b, c + d, a + c
    if r1 == 0 or r2 == 0 or c1 == 0 or (b + d) == 0:
        return 1.0
    p_obs = _hypergeom_pmf(a, r1, r2, c1)
    total = 0.0
    lo = max(0, c1 - r2)
    hi = min(r1, c1)
    for k in range(lo, hi + 1):
        p_k = _hypergeom_pmf(k, r1, r2, c1)
        if p_k <= p_obs * (1 + 1e-9):
            total += p_k
    return min(1.0, total)


def odds_ratio(a: int, b: int, c: int, d: int) -> float:
    """Haldane-Anscombe corrected odds ratio (variant vs baseline)."""
    return ((c + 0.5) * (b + 0.5)) / ((d + 0.5) * (a + 0.5))


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def cochran_armitage(groups: list[tuple[float, int, int]]) -> tuple[float, float] | None:
    """Trend test. groups = [(score, successes, n), ...]. Returns (z, two-sided p)."""
    groups = [g for g in groups if g[2] > 0]
    if len(groups) < 3:
        return None
    N = sum(n for _, _, n in groups)
    X = sum(x for _, x, _ in groups)
    if X == 0 or X == N:
        return None
    p = X / N
    T = sum(t * x for t, x, _ in groups)
    s1 = sum(t * n for t, _, n in groups)
    s2 = sum(t * t * n for t, _, n in groups)
    var = p * (1 - p) * (s2 - s1 * s1 / N)
    if var <= 0:
        return None
    z = (T - p * s1) / math.sqrt(var)
    return z, 2 * _norm_sf(abs(z))


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

SUMMARY_FIELDS = [
    "quantization",
    "bits",
    "effective_bits_per_weight",
    "category",
    "mode",
    "total_responses",
    "responses_sane",
    "responses_uncertain",
    "responses_collapsed",
    "sane_share",
    "collapsed_share",
    "mean_garbage_score",
    "han_in_sane",
    "han_in_uncertain",
    "han_in_collapsed",
    "intrusion_rate_sane",
    "wilson_lo_sane",
    "wilson_hi_sane",
    "responses_with_han",
    "intrusion_rate",
    "wilson_lo",
    "wilson_hi",
    "total_han_chars",
    "han_per_1000_output_chars",
    "han_per_1000_output_tokens",
    "mean_han_chars_in_contaminated",
    "responses_with_hiragana",
    "responses_with_katakana",
    "responses_with_hangul",
    "mean_latency_sec",
    "median_latency_sec",
    "mean_output_tokens",
    "mean_output_chars",
]


def effective_bits(rec: dict, registry_entry: dict) -> float | None:
    """Precision score on one scale for uniform and mixed variants alike.

    Preference order: value measured by mlx_lm at conversion time (recorded in the
    response or in models/config.json) > uniform bits + the affine group-64 overhead
    of 32 bits per 64 weights (0.5), which is exactly what MLX reports for the uniform
    variants (q8 -> 8.500, q3 -> 3.501, q2 -> 2.501).
    """
    for source in (rec.get("effective_bits_per_weight"), registry_entry.get("effective_bits_per_weight")):
        if source:
            return float(source)
    bits = rec.get("bits") if rec.get("bits") is not None else registry_entry.get("bits")
    if bits is None:
        return None
    quant = (rec.get("quantization") or "")
    if "g64" in quant:
        return float(bits) + 0.5
    return float(bits)


def summarize(rows: list[dict], quantization: str, bits, category: str, mode: str,
              eff_bits: float | None = None) -> dict:
    n = len(rows)
    hits = [r for r in rows if r["counts_as_leakage"]]
    han_total = sum(r["han_char_count"] for r in rows if r["counts_as_leakage"])
    out_chars = sum(r["response_chars"] for r in rows)
    out_tokens = sum(r.get("output_tokens") or 0 for r in rows)
    lat = [r.get("latency_sec") or 0.0 for r in rows]
    lo, hi = wilson(len(hits), n)

    # sanity split
    sane = [r for r in rows if r.get("sanity_verdict") == "sane"]
    uncertain = [r for r in rows if r.get("sanity_verdict") == "uncertain"]
    collapsed = [r for r in rows if r.get("sanity_verdict") == "collapsed"]
    sane_hits = [r for r in sane if r["counts_as_leakage"]]
    collapsed_hits = [r for r in collapsed if r["counts_as_leakage"]]
    uncertain_hits = [r for r in uncertain if r["counts_as_leakage"]]
    slo, shi = wilson(len(sane_hits), len(sane))
    garbage = [r.get("garbage_score") or 0.0 for r in rows]

    return {
        "quantization": quantization,
        "bits": bits if bits is not None else "",
        "effective_bits_per_weight": eff_bits if eff_bits is not None else "",
        "category": category,
        "mode": mode,
        "total_responses": n,
        "responses_sane": len(sane),
        "responses_uncertain": len(uncertain),
        "responses_collapsed": len(collapsed),
        "sane_share": round(len(sane) / n, 4) if n else 0.0,
        "collapsed_share": round(len(collapsed) / n, 4) if n else 0.0,
        "mean_garbage_score": round(statistics.fmean(garbage), 4) if garbage else 0.0,
        "han_in_sane": len(sane_hits),
        "han_in_uncertain": len(uncertain_hits),
        "han_in_collapsed": len(collapsed_hits),
        "intrusion_rate_sane": round(len(sane_hits) / len(sane), 6) if sane else 0.0,
        "wilson_lo_sane": round(slo, 6),
        "wilson_hi_sane": round(shi, 6),
        "responses_with_han": len(hits),
        "intrusion_rate": round(len(hits) / n, 6) if n else 0.0,
        "wilson_lo": round(lo, 6),
        "wilson_hi": round(hi, 6),
        "total_han_chars": han_total,
        "han_per_1000_output_chars": round(1000 * han_total / out_chars, 4) if out_chars else 0.0,
        "han_per_1000_output_tokens": round(1000 * han_total / out_tokens, 4) if out_tokens else 0.0,
        "mean_han_chars_in_contaminated": round(han_total / len(hits), 3) if hits else 0.0,
        "responses_with_hiragana": sum(1 for r in rows if r["has_hiragana"]),
        "responses_with_katakana": sum(1 for r in rows if r["has_katakana"]),
        "responses_with_hangul": sum(1 for r in rows if r["has_hangul"]),
        "mean_latency_sec": round(statistics.fmean(lat), 3) if lat else 0.0,
        "median_latency_sec": round(statistics.median(lat), 3) if lat else 0.0,
        "mean_output_tokens": round(out_tokens / n, 2) if n else 0.0,
        "mean_output_chars": round(out_chars / n, 2) if n else 0.0,
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def md_table(rows: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join([head, sep] + body)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="results/raw.jsonl")
    ap.add_argument("--output-dir", default="results/analysis")
    ap.add_argument("--intrusions", default="results/intrusions.jsonl")
    ap.add_argument("--models", default="models/config.json",
                    help="variant registry, used for effective bits/weight of mixed variants")
    ap.add_argument("--baseline", default=None, help="baseline variant name (default: highest precision present)")
    ap.add_argument("--strip-think", action="store_true",
                    help="drop <think>...</think> blocks before detection (only relevant if a "
                         "reasoning model is substituted; Qwen3-4B-Instruct-2507 emits none)")
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"{in_path} not found; run run_benchmark.py first", file=sys.stderr)
        return 1

    raw = []
    with in_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw.append(json.loads(line))
    if not raw:
        print(f"{in_path} is empty", file=sys.stderr)
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    annotated = []
    for rec in raw:
        rec = dict(rec)
        text = rec.get("response", "")
        if args.strip_think:
            text = re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.DOTALL)
            rec["analysed_response"] = text
        rec.update(detect(text, rec.get("prompt", "")))
        rec.update(sanity.assess(text))
        annotated.append(rec)

    with (out_dir / "annotated.jsonl").open("w", encoding="utf-8") as f:
        for rec in annotated:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Contaminated outputs, kept for manual semantic inspection (no translation).
    # Split by sanity verdict: a Han character inside an otherwise healthy Russian
    # answer is evidence about language selection; a Han character inside rubble is
    # only evidence that the model broke.
    intr_path = Path(args.intrusions)
    intr_path.parent.mkdir(parents=True, exist_ok=True)
    split_paths = {
        v: intr_path.with_name(intr_path.stem + f"_{v}" + intr_path.suffix)
        for v in ("sane", "uncertain", "collapsed")
    }
    handles = {v: p.open("w", encoding="utf-8") for v, p in split_paths.items()}
    n_intr = 0
    counts_by_verdict = defaultdict(int)
    with intr_path.open("w", encoding="utf-8") as f:
        for rec in annotated:
            if not rec["counts_as_leakage"]:
                continue
            n_intr += 1
            verdict = rec["sanity_verdict"]
            counts_by_verdict[verdict] += 1
            payload = json.dumps({
                "model": rec.get("model"),
                "variant": rec.get("variant"),
                "quantization": rec.get("quantization"),
                "bits": rec.get("bits"),
                "effective_bits_per_weight": rec.get("effective_bits_per_weight"),
                "prompt_id": rec.get("prompt_id"),
                "category": rec.get("category"),
                "mode": rec.get("mode"),
                "seed": rec.get("seed"),
                "prompt": rec.get("prompt"),
                "response": rec.get("response"),
                "han_char_count": rec["han_char_count"],
                "han_chars": rec["han_chars"],
                "positions": rec["positions"],
                "segments": rec["han_segments"],
                "has_hiragana": rec["has_hiragana"],
                "has_katakana": rec["has_katakana"],
                "has_hangul": rec["has_hangul"],
                "output_tokens": rec.get("output_tokens"),
                "sanity_verdict": verdict,
                "likely_global_collapse": rec["likely_global_collapse"],
                "garbage_score": rec["garbage_score"],
                "sanity_reasons": rec["sanity_reasons"],
                "sanity_signals": rec["sanity_signals"],
            }, ensure_ascii=False) + "\n"
            f.write(payload)
            handles[verdict].write(payload)
    for h in handles.values():
        h.close()

    # ---- grouping ----
    # Optional variant registry: gives effective bits/weight for mixed-precision
    # variants, where a single "bits" number does not exist.
    registry: dict[str, dict] = {}
    if args.models and Path(args.models).exists():
        for v in json.loads(Path(args.models).read_text(encoding="utf-8")).get("variants", []):
            registry[v["name"]] = v

    by_var = defaultdict(list)
    by_var_cat = defaultdict(list)
    by_var_mode = defaultdict(list)
    bits_of, quant_of, eff_of = {}, {}, {}
    for rec in annotated:
        v = rec.get("variant") or rec.get("quantization") or "unknown"
        bits_of[v] = rec.get("bits")
        quant_of[v] = rec.get("quantization", v)
        eff_of[v] = effective_bits(rec, registry.get(v, {}))
        by_var[v].append(rec)
        by_var_cat[(v, rec.get("category", "?"))].append(rec)
        by_var_mode[(v, rec.get("mode", "?"))].append(rec)

    def vsort(v: str):
        e = eff_of.get(v)
        return (-(e if e is not None else 1e9), v)

    variants = sorted(by_var, key=vsort)

    sum_var = [summarize(by_var[v], quant_of[v], bits_of[v], "ALL", "ALL", eff_of[v]) for v in variants]
    sum_cat = [
        summarize(by_var_cat[(v, c)], quant_of[v], bits_of[v], c, "ALL", eff_of[v])
        for v in variants
        for c in sorted({k[1] for k in by_var_cat if k[0] == v})
    ]
    sum_mode = [
        summarize(by_var_mode[(v, m)], quant_of[v], bits_of[v], "ALL", m, eff_of[v])
        for v in variants
        for m in sorted({k[1] for k in by_var_mode if k[0] == v})
    ]

    write_csv(out_dir / "by_quantization.csv", sum_var, SUMMARY_FIELDS)
    write_csv(out_dir / "by_quantization_category.csv", sum_cat, SUMMARY_FIELDS)
    write_csv(out_dir / "by_quantization_mode.csv", sum_mode, SUMMARY_FIELDS)

    # ---- baseline comparisons ----
    baseline = args.baseline or (variants[0] if variants else None)
    if baseline not in by_var:
        print(f"baseline {baseline!r} not present in data", file=sys.stderr)
        return 1

    comparisons = []
    categories = sorted({rec.get("category", "?") for rec in annotated})
    # "all"  = every response, comparable with the earlier q8/q3 numbers
    # "sane" = only responses the collapse detector calls healthy; this is the
    #          population where a Han character says something about language
    #          selection rather than about the model having fallen apart
    populations = {
        "all": lambda rows: rows,
        "sane": lambda rows: [r for r in rows if r.get("sanity_verdict") == "sane"],
    }
    for population, keep in populations.items():
        for v in variants:
            if v == baseline:
                continue
            for scope, base_rows_all, var_rows_all in (
                [("ALL", by_var[baseline], by_var[v])]
                + [(c, by_var_cat[(baseline, c)], by_var_cat[(v, c)]) for c in categories]
            ):
                base_rows, var_rows = keep(base_rows_all), keep(var_rows_all)
                if len(base_rows) == 0 or len(var_rows) == 0:
                    continue
                a = sum(1 for r in base_rows if r["counts_as_leakage"])
                b = len(base_rows) - a
                c_ = sum(1 for r in var_rows if r["counts_as_leakage"])
                d = len(var_rows) - c_
                comparisons.append({
                    "population": population,
                    "baseline": baseline,
                    "variant": v,
                    "scope": scope,
                    "baseline_n": len(base_rows),
                    "baseline_hits": a,
                    "baseline_rate": round(a / len(base_rows), 6),
                    "variant_n": len(var_rows),
                    "variant_hits": c_,
                    "variant_rate": round(c_ / len(var_rows), 6),
                    "odds_ratio_hc": round(odds_ratio(a, b, c_, d), 4),
                    "fisher_p_two_sided": round(fisher_exact(a, b, c_, d), 6),
                    "total_events": a + c_,
                    "powered": "yes" if (a + c_) >= 10 else "no",
                })
    write_csv(out_dir / "comparisons.csv", comparisons, list(comparisons[0].keys()) if comparisons else ["baseline"])

    # Trend is scored on effective bits/weight so that mixed-precision variants sit on
    # the same axis as the uniform ones.
    trend = cochran_armitage([
        (eff_of[v], sum(1 for r in by_var[v] if r["counts_as_leakage"]), len(by_var[v]))
        for v in variants
        if eff_of.get(v) is not None
    ])
    trend_sane = cochran_armitage([
        (eff_of[v],
         sum(1 for r in by_var[v] if r["counts_as_leakage"] and r.get("sanity_verdict") == "sane"),
         sum(1 for r in by_var[v] if r.get("sanity_verdict") == "sane"))
        for v in variants
        if eff_of.get(v) is not None
    ])

    # ---- report ----
    total_events = sum(s["responses_with_han"] for s in sum_var)
    lines = []
    lines.append("# Language leakage vs quantization — results\n")
    lines.append(f"- input: `{in_path}`")
    lines.append(f"- responses analysed: **{len(annotated)}**")
    lines.append(f"- models: {', '.join(sorted({r.get('model', '?') for r in annotated}))}")
    lines.append(f"- variants: {', '.join(variants)} (baseline: **{baseline}**)")
    lines.append(f"- responses containing Han characters: **{total_events}**")
    lines.append(f"- contaminated responses written to `{intr_path}` ({n_intr}); "
                 f"split by sanity verdict into "
                 + ", ".join(f"`{p.name}` ({counts_by_verdict.get(v, 0)})" for v, p in split_paths.items())
                 + "\n")

    lines.append("## Semantic sanity (collapse detector)\n")
    lines.append("`sane` / `uncertain` / `collapsed` from cheap character and word statistics. "
                 "`uncertain` is a genuine third state: too short, mostly code, or contradictory "
                 "signals. Only `sane` responses are treated as evidence about language selection.\n")
    lines.append(md_table(sum_var, [
        "quantization", "effective_bits_per_weight", "total_responses", "responses_sane",
        "responses_uncertain", "responses_collapsed", "sane_share", "mean_garbage_score",
    ]))

    lines.append("\n## Han intrusions split by sanity verdict\n")
    lines.append("`han_in_sane` is the number that matters: a foreign token inside an otherwise "
                 "healthy Russian answer. `han_in_collapsed` mostly reflects the model being broken.\n")
    lines.append(md_table(sum_var, [
        "quantization", "effective_bits_per_weight", "responses_with_han", "han_in_sane",
        "han_in_uncertain", "han_in_collapsed", "responses_sane", "intrusion_rate_sane",
        "wilson_lo_sane", "wilson_hi_sane",
    ]))

    lines.append("\n## Per quantization variant (all responses)\n")
    lines.append(md_table(sum_var, [
        "quantization", "bits", "effective_bits_per_weight", "total_responses",
        "responses_with_han", "intrusion_rate", "wilson_lo", "wilson_hi",
        "han_per_1000_output_chars", "han_per_1000_output_tokens",
        "mean_han_chars_in_contaminated", "mean_latency_sec", "mean_output_tokens",
    ]))
    lines.append("\n## Per quantization x prompt category\n")
    lines.append(md_table(sum_cat, [
        "quantization", "effective_bits_per_weight", "category", "total_responses",
        "responses_sane", "responses_with_han", "han_in_sane", "intrusion_rate",
        "wilson_lo", "wilson_hi",
    ]))
    lines.append("\n## Per quantization x decoding mode\n")
    lines.append(md_table(sum_mode, [
        "quantization", "effective_bits_per_weight", "mode", "total_responses",
        "responses_sane", "responses_with_han", "han_in_sane", "intrusion_rate",
        "wilson_lo", "wilson_hi",
    ]))

    lines.append("\n## Baseline vs quantized (Fisher exact, two-sided)\n")
    if comparisons:
        for population in ("all", "sane"):
            rows = [c for c in comparisons if c["scope"] == "ALL" and c["population"] == population]
            if not rows:
                continue
            label = ("all responses" if population == "all"
                     else "sane responses only — the language-selection population")
            lines.append(f"\n**Population: {label}**\n")
            lines.append(md_table(rows, [
                "variant", "baseline_n", "baseline_hits", "baseline_rate",
                "variant_n", "variant_hits", "variant_rate", "odds_ratio_hc",
                "fisher_p_two_sided", "total_events", "powered",
            ]))
        lines.append("\nPer-category comparisons, both populations, are in `comparisons.csv`.")
    else:
        lines.append("_Only one variant present — nothing to compare._")

    lines.append("\n## Trend across effective bits/weight\n")
    for label, t in (("all responses", trend), ("sane responses only", trend_sane)):
        if t is None:
            lines.append(f"- _{label}: trend test not computed (fewer than three variants, or "
                         "zero/complete separation of events)._")
        else:
            z, p = t
            direction = ("rate increases as precision decreases" if z < 0
                         else "rate increases as precision increases")
            lines.append(f"- {label}: Cochran-Armitage z = {z:.3f}, two-sided p = {p:.5f} ({direction}).")

    lines.append("\n## Statistical power\n")
    if total_events == 0:
        lines.append("**No Han intrusions observed at all.** No claim about quantization can be made "
                     "from this run in either direction; the experiment only bounds the rate from above "
                     "(see the Wilson upper bounds in the table). Increase the number of sampling seeds, "
                     "prompts or max_tokens before drawing conclusions.")
    elif total_events < 10:
        lines.append(f"**Only {total_events} contaminated responses in total.** This is too few for a "
                     "meaningful significance test; p-values above are reported for completeness only "
                     "and should not be interpreted. Treat the contaminated outputs as qualitative "
                     "material and collect more samples.")
    else:
        lines.append(f"{total_events} contaminated responses in total. Fisher exact is appropriate for "
                     "these counts; note that per-category tests are unadjusted for multiple comparisons "
                     "(there are {} of them).".format(len([c for c in comparisons if c['scope'] != 'ALL'])))

    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"analysed {len(annotated)} responses from {in_path}")
    print(f"  Han-contaminated responses: {total_events} "
          f"(sane={counts_by_verdict.get('sane', 0)} uncertain={counts_by_verdict.get('uncertain', 0)} "
          f"collapsed={counts_by_verdict.get('collapsed', 0)})")
    print(f"  wrote {out_dir}/report.md, by_quantization*.csv, comparisons.csv, annotated.jsonl")
    print(f"  wrote {intr_path} ({n_intr} records) + {', '.join(p.name for p in split_paths.values())}")
    print(f"  {'variant':<22} {'eff.bits':>8} {'n':>5} {'sane':>5} {'collapsed':>9} "
          f"{'han':>4} {'han/sane':>8}")
    for v, s in zip(variants, sum_var):
        eff = s["effective_bits_per_weight"]
        print(f"  {v:<22} {eff if eff != '' else '?':>8} {s['total_responses']:>5} "
              f"{s['responses_sane']:>5} {s['responses_collapsed']:>9} "
              f"{s['responses_with_han']:>4} {s['han_in_sane']:>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
