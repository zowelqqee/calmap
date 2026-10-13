#!/usr/bin/env python3
"""Run the language-leakage benchmark over several quantization variants of ONE model.

Everything except quantization is held fixed: same prompts, same system prompt,
same chat template, same tokenizer, same seeds, same sampler settings, same
max_tokens. Models are loaded one at a time and released before the next one,
so an 8 GB M1 never holds two checkpoints at once.

    python run_benchmark.py --models models/config.json \
                            --prompts prompts.jsonl \
                            --output results/raw.jsonl

    python run_benchmark.py --smoke        # tiny end-to-end pipeline check

Modes:
    deterministic - temperature 0 (greedy). One run per prompt; the seed field
                    is recorded but does not influence sampling.
    sampling      - temperature 0.7 / top_p 0.95 with N fixed seeds per prompt.
                    Leakage is a rare stochastic event, so this is where most
                    of the signal is expected.

The script appends to the output file and skips work already present there,
so an interrupted run can simply be restarted with the same command.
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Fixed across every model, mode and seed. Changing this invalidates comparisons.
SYSTEM_PROMPT = (
    "Ты — инженерный ассистент. Отвечай на русском языке, кратко и по существу."
)

DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.95
DEFAULT_MAX_TOKENS = 160
DEFAULT_SAMPLING_SEEDS = 3
MAX_PROMPT_TOKENS = 2048  # keep the context small; this is an 8 GB machine


# --------------------------------------------------------------------------
# io helpers
# --------------------------------------------------------------------------


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"warning: {path}:{line_no} is not valid JSON ({exc}); skipping", file=sys.stderr)
    return out


def record_key(rec: dict) -> tuple:
    return (rec.get("variant"), rec.get("prompt_id"), rec.get("mode"), rec.get("seed"))


def encode_chat(tokenizer, user_prompt: str) -> list[int]:
    """Apply the model's own chat template. Returns a list of token ids."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    apply = getattr(tokenizer, "apply_chat_template", None)
    if apply is None:  # pragma: no cover - TokenizerWrapper normally delegates
        apply = tokenizer._tokenizer.apply_chat_template
    ids = apply(messages, add_generation_prompt=True)
    # transformers has returned plain lists, BatchEncoding and tensors over the
    # years depending on version and flags; normalise all of them.
    if isinstance(ids, dict):
        ids = ids["input_ids"]
    if hasattr(ids, "tolist"):
        ids = ids.tolist()
    while isinstance(ids, (list, tuple)) and len(ids) == 1 and isinstance(ids[0], (list, tuple)):
        ids = ids[0]
    return [int(t) for t in ids]


# --------------------------------------------------------------------------
# benchmark
# --------------------------------------------------------------------------


def make_jobs(prompts: list[dict], modes: list[str], seeds: list[int]) -> list[dict]:
    jobs = []
    for p in prompts:
        if "deterministic" in modes:
            jobs.append({"prompt": p, "mode": "deterministic", "seed": 0})
        if "sampling" in modes:
            for s in seeds:
                jobs.append({"prompt": p, "mode": "sampling", "seed": s})
    return jobs


def run_variant(
    variant: dict,
    cfg: dict,
    jobs: list[dict],
    out_handle,
    done: set,
    args,
) -> int:
    import mlx.core as mx
    from mlx_lm import load, stream_generate
    from mlx_lm.sample_utils import make_sampler

    path = variant["path"]
    if not Path(path).exists():
        print(f"!! {variant['name']}: {path} not found - run ./quantize_models.sh first. Skipping.")
        return 0

    pending = [j for j in jobs if (variant["name"], j["prompt"]["prompt_id"], j["mode"], j["seed"]) not in done]
    if not pending:
        print(f"== {variant['name']}: nothing to do (all {len(jobs)} runs already in output)")
        return 0

    print(f"== {variant['name']} ({variant['quantization']}) loading {path}")
    t_load = time.perf_counter()
    model, tokenizer = load(path)
    print(f"   loaded in {time.perf_counter() - t_load:.1f}s; {len(pending)}/{len(jobs)} runs pending")

    if hasattr(mx, "reset_peak_memory"):
        mx.reset_peak_memory()

    written = 0
    t_start = time.perf_counter()
    total_tokens = 0
    try:
        for i, job in enumerate(pending, 1):
            p = job["prompt"]
            temp = 0.0 if job["mode"] == "deterministic" else args.temperature
            top_p = 0.0 if job["mode"] == "deterministic" else args.top_p

            ids = encode_chat(tokenizer, p["prompt"])
            if len(ids) > MAX_PROMPT_TOKENS:
                print(f"   !! {p['prompt_id']} is {len(ids)} tokens (> {MAX_PROMPT_TOKENS}), skipping")
                continue

            sampler = make_sampler(temp=temp, top_p=top_p)
            mx.random.seed(job["seed"])

            chunks: list[str] = []
            last = None
            t0 = time.perf_counter()
            for resp in stream_generate(
                model, tokenizer, prompt=ids, max_tokens=args.max_tokens, sampler=sampler
            ):
                chunks.append(resp.text)
                last = resp
            latency = time.perf_counter() - t0
            response = "".join(chunks)

            rec = {
                "model": cfg["source_model"],
                "variant": variant["name"],
                "quantization": variant["quantization"],
                "bits": variant.get("bits"),
                # present for mixed-precision variants, where a single "bits" number
                # does not exist; measured by mlx_lm at conversion time
                "effective_bits_per_weight": variant.get("effective_bits_per_weight"),
                "model_path": path,
                "prompt_id": p["prompt_id"],
                "category": p["category"],
                "mode": job["mode"],
                "seed": job["seed"],
                "temperature": temp,
                "top_p": top_p,
                "max_tokens": args.max_tokens,
                "system_prompt": SYSTEM_PROMPT,
                "prompt": p["prompt"],
                "response": response,
                "latency_sec": round(latency, 4),
                "prompt_tokens": getattr(last, "prompt_tokens", len(ids)),
                "output_tokens": getattr(last, "generation_tokens", 0),
                "generation_tps": round(getattr(last, "generation_tps", 0.0), 3),
                "peak_memory_gb": round(getattr(last, "peak_memory", 0.0), 3),
                "finish_reason": getattr(last, "finish_reason", None),
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            out_handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_handle.flush()
            written += 1
            total_tokens += rec["output_tokens"]

            if i == 1 or i % 10 == 0 or i == len(pending):
                elapsed = time.perf_counter() - t_start
                eta = elapsed / i * (len(pending) - i)
                print(
                    f"   [{i}/{len(pending)}] {p['prompt_id']} {job['mode']}/seed={job['seed']} "
                    f"{rec['output_tokens']}tok {latency:.1f}s "
                    f"| {total_tokens / max(elapsed, 1e-9):.1f} tok/s avg | eta {eta / 60:.1f} min"
                )
    finally:
        del model
        del tokenizer
        gc.collect()
        if hasattr(mx, "clear_cache"):
            mx.clear_cache()

    print(f"   {variant['name']} done: {written} responses in {(time.perf_counter() - t_start) / 60:.1f} min")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="models/config.json", help="model/variant config")
    ap.add_argument("--prompts", default="prompts.jsonl", help="prompt dataset")
    ap.add_argument("--output", default="results/raw.jsonl", help="output JSONL (appended, resumable)")
    ap.add_argument("--variants", default=None, help="comma separated variant names, default: all in config")
    ap.add_argument("--modes", default="deterministic,sampling", help="deterministic,sampling")
    ap.add_argument("--sampling-seeds", type=int, default=DEFAULT_SAMPLING_SEEDS, help="seeds per prompt in sampling mode")
    ap.add_argument("--seed-base", type=int, default=1000, help="first sampling seed; seeds are base..base+n-1")
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    ap.add_argument("--top-p", type=float, default=DEFAULT_TOP_P)
    ap.add_argument("--max-prompts", type=int, default=None, help="use only the first N prompts per category")
    ap.add_argument("--smoke", action="store_true", help="tiny end-to-end check: 3 prompts, 2 variants, short outputs")
    ap.add_argument("--overwrite", action="store_true", help="truncate the output file instead of resuming")
    args = ap.parse_args()

    cfg = json.loads(Path(args.models).read_text(encoding="utf-8"))
    prompts = read_jsonl(Path(args.prompts))
    if not prompts:
        print(f"no prompts in {args.prompts}; run generate_prompts.py first", file=sys.stderr)
        return 1

    variants = cfg["variants"]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    if args.smoke:
        # one prompt from each of the first three categories
        picked, seen = [], set()
        for p in prompts:
            if p["category"] not in seen:
                seen.add(p["category"])
                picked.append(p)
            if len(picked) == 3:
                break
        prompts = picked
        variants = [v for v in variants if Path(v["path"]).exists()][:2] or variants[:2]
        args.sampling_seeds = 1
        args.max_tokens = min(args.max_tokens, 64)
        if args.output == "results/raw.jsonl":
            args.output = "results/smoke.jsonl"
        print("SMOKE MODE: 3 prompts, <=2 variants, 1 sampling seed, max_tokens="
              f"{args.max_tokens}, output={args.output}")

    if args.variants:
        wanted = {v.strip() for v in args.variants.split(",")}
        variants = [v for v in variants if v["name"] in wanted]
        missing = wanted - {v["name"] for v in variants}
        if missing:
            print(f"unknown variant(s): {sorted(missing)}", file=sys.stderr)
            return 1

    if args.max_prompts:
        per_cat: dict[str, int] = {}
        kept = []
        for p in prompts:
            n = per_cat.get(p["category"], 0)
            if n < args.max_prompts:
                per_cat[p["category"]] = n + 1
                kept.append(p)
        prompts = kept

    seeds = [args.seed_base + i for i in range(args.sampling_seeds)]
    jobs = make_jobs(prompts, modes, seeds)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = [] if args.overwrite else read_jsonl(out_path)
    done = {record_key(r) for r in existing}

    print(f"model     : {cfg['source_model']}")
    print(f"variants  : {[v['name'] for v in variants]}")
    print(f"prompts   : {len(prompts)}  modes: {modes}  sampling seeds: {seeds}")
    print(f"runs      : {len(jobs)} per variant, {len(jobs) * len(variants)} total "
          f"({len(done)} already in {out_path})")
    print(f"generation: max_tokens={args.max_tokens} temp={args.temperature} top_p={args.top_p}")
    print(f"host      : {platform.platform()} python {platform.python_version()}")
    print()

    mode_flag = "w" if args.overwrite else "a"
    total_written = 0
    t0 = time.perf_counter()
    with out_path.open(mode_flag, encoding="utf-8") as fh:
        for variant in variants:
            total_written += run_variant(variant, cfg, jobs, fh, done, args)

    print(f"\nwrote {total_written} new responses to {out_path} "
          f"in {(time.perf_counter() - t0) / 60:.1f} min")
    print(f"next: python analyze.py --input {out_path} --output-dir results/analysis")
    return 0


if __name__ == "__main__":
    sys.exit(main())
