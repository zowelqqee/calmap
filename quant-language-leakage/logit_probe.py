#!/usr/bin/env python3
"""Sequence-level language-selection probe.

At a decision point where Russian, English and Chinese realizations of the SAME concept
compete, measure how much probability mass the model puts on each, and how that margin
moves with effective precision. This is far more sensitive than waiting for a rare
sampling event: it reads the margin directly, whether or not leakage ever happens.

Multi-token safe. Every candidate is tokenized first and scored as a full sequence:

    log P(candidate | context) = sum_i log P(t_i | context, t_<i)

so a three-token Chinese form is compared honestly against a one-token Russian one.
Both the summed log-probability (the actual probability of emitting that continuation)
and the length-normalised mean are reported, along with the tokenization of every
candidate, so length effects stay visible instead of hidden.

    python logit_probe.py --variants q8,q3,mixed_2_6,q2 --output results/logit_probe.jsonl

Variants missing from disk can be converted on demand and removed again afterwards:

    python logit_probe.py --variants q8,q3,mixed_2_6,q2 --transient q8,q3

--transient only ever deletes a directory this run created itself.
"""

from __future__ import annotations

import argparse
import gc
import json
import shutil
import sys
from pathlib import Path

from run_benchmark import SYSTEM_PROMPT, encode_chat  # identical template and system prompt

# --------------------------------------------------------------------------
# Probes: Russian context, forced Russian assistant prefix stopping right before the
# target word. Each concept appears in a pure-Russian and a code-switched context, since
# the hypothesis is specifically about code-switched input.
# --------------------------------------------------------------------------

PROBES = [
    {
        "id": "second__pure_ru",
        "concept": "второй",
        "user": "Первый полный прогон уже завершён, сейчас идёт следующий по счёту. "
                "Скажи одним предложением, какой прогон выполняется. Ответь на русском языке.",
        "prefix": "Сейчас выполняется ",
        "candidates": {"ru": ["второй"], "en": ["second"], "zh": ["第二个", "第二"]},
    },
    {
        "id": "second__code_switched",
        "concept": "второй",
        "user": "Второй full quality run нужен, чтобы итоговый JSON включал timing и incident "
                "metrics для всех режимов. Скажи одним предложением, какой run сейчас идёт. "
                "Ответь на русском языке.",
        "prefix": "Сейчас идёт ",
        "candidates": {"ru": ["второй"], "en": ["second"], "zh": ["第二个", "第二"]},
    },
    {
        "id": "now__pure_ru",
        "concept": "сейчас",
        "user": "Скажи одним предложением, что задача запущена и продолжается в данный момент. "
                "Ответь на русском языке.",
        "prefix": "Задача запущена и ",
        "candidates": {"ru": ["сейчас"], "en": ["now"], "zh": ["现在", "正"]},
    },
    {
        "id": "running__code_switched",
        "concept": "выполняется",
        "user": "Второй full quality run сейчас в процессе. Опиши состояние одним предложением: "
                "процесс запущен и не завершён. Ответь на русском языке.",
        "prefix": "Процесс ",
        "candidates": {"ru": ["выполняется", "идёт"], "en": ["running", "is"], "zh": ["运行", "正在运行"]},
    },
    {
        "id": "finished__pure_ru",
        "concept": "завершён",
        "user": "Скажи одним предложением, что первый прогон полностью закончился без ошибок. "
                "Ответь на русском языке.",
        "prefix": "Первый прогон ",
        "candidates": {"ru": ["завершён", "завершен"], "en": ["finished", "completed"], "zh": ["完成", "已完成"]},
    },
    {
        "id": "error__code_switched",
        "concept": "ошибка",
        "user": "В логе ingest-worker записано `retry_count=3 timeout`. Скажи одним предложением, "
                "что произошло. Ответь на русском языке.",
        "prefix": "Произошла ",
        "candidates": {"ru": ["ошибка"], "en": ["error"], "zh": ["错误"]},
    },
    {
        "id": "error__json_context",
        "concept": "ошибка",
        "user": 'Валидация упала на записи {"run_id": "", "timing": 0}. Скажи одним предложением, '
                "в чём проблема. Ответь на русском языке.",
        "prefix": "Здесь ",
        "candidates": {"ru": ["ошибка"], "en": ["error"], "zh": ["错误"]},
    },
]


def to_list(ids) -> list[int]:
    if hasattr(ids, "tolist"):
        ids = ids.tolist()
    while isinstance(ids, (list, tuple)) and len(ids) == 1 and isinstance(ids[0], (list, tuple)):
        ids = ids[0]
    return [int(t) for t in ids]


def score_candidate(model, tokenizer, ctx_ids: list[int], surface: str) -> dict | None:
    """Autoregressive sequence log-probability of `surface` continuing `ctx_ids`."""
    import mlx.core as mx
    import mlx.nn as nn

    cand_ids = to_list(tokenizer.encode(surface, add_special_tokens=False))
    if not cand_ids:
        return None

    full = mx.array([ctx_ids + cand_ids])
    logits = model(full)[0].astype(mx.float32)          # (seq, vocab)
    logprobs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
    mx.eval(logprobs)

    start = len(ctx_ids) - 1                            # position predicting cand_ids[0]
    total = 0.0
    per_token = []
    for i, tid in enumerate(cand_ids):
        lp = float(logprobs[start + i, tid])
        per_token.append(round(lp, 4))
        total += lp

    first_row = logprobs[start]
    rank = int(mx.sum(first_row > first_row[cand_ids[0]]).item())

    return {
        "surface": surface,
        "token_ids": cand_ids,
        "tokens": [tokenizer.decode([t]) for t in cand_ids],
        "n_tokens": len(cand_ids),
        "seq_logprob": round(total, 4),
        "mean_token_logprob": round(total / len(cand_ids), 4),
        "per_token_logprob": per_token,
        "first_token_rank": rank,
        "first_token_logprob": per_token[0],
    }


def best_for_language(model, tokenizer, ctx_ids: list[int], surfaces: list[str]) -> dict | None:
    """Score every surface form (bare and space-prefixed); keep the most likely one."""
    best = None
    tried = []
    for s in surfaces:
        for variant in (s, " " + s):
            scored = score_candidate(model, tokenizer, ctx_ids, variant)
            if scored is None:
                continue
            tried.append({"surface": variant, "seq_logprob": scored["seq_logprob"],
                          "n_tokens": scored["n_tokens"]})
            if best is None or scored["seq_logprob"] > best["seq_logprob"]:
                best = scored
    if best is not None:
        best["all_surfaces_tried"] = tried
    return best


def probe_model(path: str, variant: dict, top_k: int) -> list[dict]:
    import mlx.core as mx
    from mlx_lm import load

    print(f"== {variant['name']}  ({variant.get('quantization')}, "
          f"eff.bits={variant.get('effective_bits_per_weight') or variant.get('bits')})")
    model, tokenizer = load(path)
    out = []
    try:
        for probe in PROBES:
            ctx_ids = encode_chat(tokenizer, probe["user"])
            ctx_ids = ctx_ids + to_list(tokenizer.encode(probe["prefix"], add_special_tokens=False))

            scored = {
                lang: best_for_language(model, tokenizer, ctx_ids, surfaces)
                for lang, surfaces in probe["candidates"].items()
            }
            if any(v is None for v in scored.values()):
                print(f"   !! {probe['id']}: a candidate failed to tokenize, skipping")
                continue

            ru, en, zh = scored["ru"], scored["en"], scored["zh"]
            ranked = sorted(scored.items(), key=lambda kv: -kv[1]["seq_logprob"])
            ru_rank_among_candidates = [lang for lang, _ in ranked].index("ru")

            # top-k at the first decision point, for context
            logits = model(mx.array([ctx_ids]))[0, -1, :].astype(mx.float32)
            order = mx.argsort(-logits)[:top_k]
            lp = logits - mx.logsumexp(logits)
            mx.eval(order, lp)
            top = [{"token_id": int(t), "token": tokenizer.decode([int(t)]),
                    "logprob": round(float(lp[int(t)]), 4)} for t in order.tolist()]

            rec = {
                "variant": variant["name"],
                "quantization": variant.get("quantization"),
                "bits": variant.get("bits"),
                "effective_bits_per_weight": variant.get("effective_bits_per_weight"),
                "probe_id": probe["id"],
                "concept": probe["concept"],
                "prefix": probe["prefix"],
                "context_tokens": len(ctx_ids),
                "ru": ru, "en": en, "zh": zh,
                "margin_ru_zh": round(ru["seq_logprob"] - zh["seq_logprob"], 4),
                "margin_ru_en": round(ru["seq_logprob"] - en["seq_logprob"], 4),
                "margin_ru_zh_mean": round(ru["mean_token_logprob"] - zh["mean_token_logprob"], 4),
                "margin_ru_en_mean": round(ru["mean_token_logprob"] - en["mean_token_logprob"], 4),
                "ru_first_token_rank": ru["first_token_rank"],
                "zh_first_token_rank": zh["first_token_rank"],
                "ru_rank_among_candidate_languages": ru_rank_among_candidates,
                "top_k_first_position": top,
            }
            out.append(rec)
            print(f"   {probe['id']:<26} ru={ru['seq_logprob']:>8.3f}({ru['n_tokens']}t) "
                  f"en={en['seq_logprob']:>8.3f}({en['n_tokens']}t) "
                  f"zh={zh['seq_logprob']:>8.3f}({zh['n_tokens']}t)  "
                  f"ru-zh={rec['margin_ru_zh']:>7.3f}  ru_rank={ru['first_token_rank']}")
    finally:
        del model
        del tokenizer
        gc.collect()
        if hasattr(mx, "clear_cache"):
            mx.clear_cache()
    return out


def convert_uniform(variant: dict, source: str, group_size: int) -> bool:
    """Convert a missing uniform variant on demand. Returns True if it was created."""
    from mlx_lm.convert import convert

    bits = variant.get("bits")
    if bits is None:
        print(f"   !! {variant['name']} has no uniform bit width; cannot auto-convert")
        return False
    need = 4.022e9 * (bits + 0.5) / 8 * 1.05
    free = shutil.disk_usage(".").free
    if free < need:
        print(f"   !! not enough disk for {variant['name']}: need ~{need / 2**30:.1f} GiB, "
              f"have {free / 2**30:.1f} GiB")
        return False
    print(f"   converting {variant['name']} ({bits}-bit) from {source} ...")
    convert(hf_path=source, mlx_path=variant["path"], quantize=True,
            q_group_size=group_size, q_bits=bits, q_mode="affine")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="models/config.json")
    ap.add_argument("--output", default="results/logit_probe.jsonl")
    ap.add_argument("--variants", default=None, help="comma separated variant names")
    ap.add_argument("--transient", default=None,
                    help="variants to convert on demand and delete again afterwards")
    ap.add_argument("--top-k", type=int, default=15)
    ap.add_argument("--group-size", type=int, default=64)
    args = ap.parse_args()

    cfg = json.loads(Path(args.models).read_text(encoding="utf-8"))
    source = cfg.get("source_model", "Qwen/Qwen3-4B-Instruct-2507")
    variants = cfg["variants"]
    if args.variants:
        wanted = [v.strip() for v in args.variants.split(",")]
        by_name = {v["name"]: v for v in variants}
        missing = [w for w in wanted if w not in by_name]
        if missing:
            print(f"unknown variant(s): {missing}", file=sys.stderr)
            return 1
        variants = [by_name[w] for w in wanted]
    transient = {v.strip() for v in args.transient.split(",")} if args.transient else set()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # resume: keep whatever is already in the output file, skip those (variant, probe) pairs
    existing: list[dict] = []
    if out_path.exists():
        existing = [json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if existing:
            print(f"resuming: {len(existing)} probe results already in {out_path}")
    done = {(r["variant"], r["probe_id"]) for r in existing}

    records: list[dict] = list(existing)
    for variant in variants:
        if all((variant["name"], p["id"]) in done for p in PROBES):
            print(f"-- {variant['name']}: already probed, skipping")
            continue
        path = Path(variant["path"])
        created_here = False
        if not path.exists():
            if variant["name"] not in transient:
                print(f"-- {variant['name']}: {path} not on disk, skipping "
                      f"(add it to --transient to convert on demand)")
                continue
            if not convert_uniform(variant, source, args.group_size):
                continue
            created_here = True
        try:
            records.extend(probe_model(str(path), variant, args.top_k))
        finally:
            if created_here and variant["name"] in transient:
                shutil.rmtree(path, ignore_errors=True)
                print(f"   removed {path} (transient); "
                      f"free disk now {shutil.disk_usage('.').free / 2**30:.1f} GiB")

    if not records:
        print("no variants probed", file=sys.stderr)
        return 1
    # de-duplicate, last write wins
    dedup = {(r["variant"], r["probe_id"]): r for r in records}
    records = list(dedup.values())

    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\nwrote {out_path} ({len(records)} probe results)")
    print(f"summarise with: python logit_report.py --input {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
