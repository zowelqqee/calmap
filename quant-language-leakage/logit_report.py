#!/usr/bin/env python3
"""Summarise logit_probe.jsonl: how does the RU-vs-ZH language margin move with precision?

    python logit_report.py --input results/logit_probe.jsonl --output-dir results/analysis

Writes a per-probe margin matrix (one column per variant) and a per-variant summary,
as CSV and as a markdown table on stdout.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def md_table(rows: list[list], header: list[str]) -> str:
    out = ["| " + " | ".join(str(h) for h in header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="results/logit_probe.jsonl")
    ap.add_argument("--output-dir", default="results/analysis")
    args = ap.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"{path} not found; run logit_probe.py first", file=sys.stderr)
        return 1
    recs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not recs:
        print(f"{path} is empty", file=sys.stderr)
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    eff = {}
    for r in recs:
        e = r.get("effective_bits_per_weight")
        if e is None and r.get("bits") is not None:
            e = r["bits"] + 0.5  # affine g64 scale+bias overhead, as MLX reports it
        eff[r["variant"]] = e
    variants = sorted(eff, key=lambda v: -(eff[v] if eff[v] is not None else 1e9))
    probes = sorted({r["probe_id"] for r in recs})

    by = {(r["variant"], r["probe_id"]): r for r in recs}

    # --- per-probe margin matrix ---
    matrix_rows = []
    for p in probes:
        row = [p, next((by[(v, p)]["concept"] for v in variants if (v, p) in by), "")]
        for v in variants:
            r = by.get((v, p))
            row.append(f"{r['margin_ru_zh']:+.3f}" if r else "")
        matrix_rows.append(row)
    header = ["probe_id", "concept"] + [f"{v} ({eff[v]})" for v in variants]

    with (out_dir / "logit_margin_matrix.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["probe_id", "concept"] + variants)
        w.writerow(["", "effective_bits_per_weight"] + [eff[v] for v in variants])
        for row in matrix_rows:
            w.writerow(row)

    # --- per-variant summary ---
    summary = []
    for v in variants:
        rs = [r for r in recs if r["variant"] == v]
        if not rs:
            continue
        m_zh = [r["margin_ru_zh"] for r in rs]
        m_en = [r["margin_ru_en"] for r in rs]
        summary.append({
            "variant": v,
            "effective_bits_per_weight": eff[v],
            "n_probes": len(rs),
            "mean_margin_ru_zh": round(statistics.fmean(m_zh), 4),
            "median_margin_ru_zh": round(statistics.median(m_zh), 4),
            "min_margin_ru_zh": round(min(m_zh), 4),
            "probes_with_negative_ru_zh": sum(1 for m in m_zh if m < 0),
            "mean_margin_ru_en": round(statistics.fmean(m_en), 4),
            "mean_ru_first_token_rank": round(statistics.fmean([r["ru_first_token_rank"] for r in rs]), 2),
            "mean_zh_first_token_rank": round(statistics.fmean([r["zh_first_token_rank"] for r in rs]), 2),
            "probes_where_ru_not_top_language": sum(
                1 for r in rs if r["ru_rank_among_candidate_languages"] != 0),
        })

    fields = list(summary[0].keys())
    with (out_dir / "logit_margin_by_variant.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(summary)

    print("## RU−ZH sequence log-prob margin per probe (positive = Russian preferred)\n")
    print(md_table(matrix_rows, header))
    print("\n## Per variant\n")
    print(md_table([[s[k] for k in fields] for s in summary], fields))
    print(f"\nwrote {out_dir}/logit_margin_matrix.csv and {out_dir}/logit_margin_by_variant.csv")

    # tokenization reference, so nobody has to trust that candidates are single tokens
    print("\n## Candidate tokenization (from the first variant probed)\n")
    first = variants[0]
    seen = set()
    tok_rows = []
    for r in recs:
        if r["variant"] != first:
            continue
        for lang in ("ru", "en", "zh"):
            c = r[lang]
            key = (lang, c["surface"])
            if key in seen:
                continue
            seen.add(key)
            tok_rows.append([lang, repr(c["surface"]), c["n_tokens"], " | ".join(repr(t) for t in c["tokens"])])
    print(md_table(tok_rows, ["lang", "surface", "n_tokens", "tokens"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
