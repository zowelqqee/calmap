#!/usr/bin/env python3
"""Work out exactly what a mixed-precision quantization recipe does to THIS model,
before spending disk and time on a conversion.

Reads the real predicate out of the installed mlx-lm (`mixed_quant_predicate_builder`),
applies it to every quantizable module of the model, and reports which modules land at
which bit width plus the resulting effective bits/weight.

Any already-converted variant of the same architecture can serve as the module-tree
reference (module paths and shapes are identical across bit widths), so this does not
require the 8 GB bf16 checkpoint to be resident.

    python inspect_quant_plan.py --ref models/qwen3-4b-instruct-2507-q2 --recipe mixed_2_6
    python inspect_quant_plan.py --ref ... --recipe mixed_2_6 --embed-bits 6
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import mlx.nn as nn
from mlx_lm import load
from mlx_lm.convert import QUANT_RECIPES, mixed_quant_predicate_builder

# affine quantization stores one fp16 scale and one fp16 bias per group
OVERHEAD_BITS_PER_GROUP = 32


def unpacked_shape(module: nn.Module) -> tuple[int, int] | None:
    """(rows, cols) of the logical weight matrix, for both dense and already-quantized modules."""
    if not hasattr(module, "weight"):
        return None
    w = module.weight
    if len(w.shape) != 2:
        return None
    if isinstance(module, (nn.QuantizedLinear, nn.QuantizedEmbedding)):
        # packed into uint32: cols_packed = cols * bits / 32
        return (w.shape[0], w.shape[1] * 32 // module.bits)
    return (w.shape[0], w.shape[1])


def build_plan(model, recipe: str, group_size: int, embed_bits: int | None,
               low_modules=None, low_layers: str = "lowsens") -> dict:
    from quantize_mixed import predicate_from_model

    predicate, _ = predicate_from_model(recipe, model, group_size, embed_bits,
                                        low_modules, low_layers)

    rows = []
    for path, module in model.named_modules():
        # A fresh bf16 model exposes to_quantized; an already-converted reference model
        # has the quantized classes instead. Both describe the same module tree.
        quantizable = hasattr(module, "to_quantized") or isinstance(
            module, (nn.QuantizedLinear, nn.QuantizedEmbedding)
        )
        if not quantizable:
            continue
        shape = unpacked_shape(module)
        if shape is None:
            continue
        rows_, cols = shape
        if cols % group_size != 0:
            rows.append({"path": path, "params": rows_ * cols, "bits": None, "skipped": True})
            continue
        params = predicate(path, module)
        bits = params["bits"] if isinstance(params, dict) else None
        source = "embed-override" if (embed_bits is not None and
                                      ("embed_tokens" in path or "lm_head" in path)) else "recipe"
        rows.append({
            "path": path,
            "params": rows_ * cols,
            "shape": [rows_, cols],
            "bits": bits,
            "source": source,
            "skipped": False,
        })
    return {"rows": rows, "group_size": group_size, "recipe": recipe, "embed_bits": embed_bits}


def summarize(plan: dict) -> dict:
    gs = plan["group_size"]
    by_bits: dict[int, int] = defaultdict(int)
    by_kind: dict[tuple[str, int], int] = defaultdict(int)
    skipped = 0
    total_params = 0
    total_bits = 0.0
    for r in plan["rows"]:
        total_params += r["params"]
        if r["skipped"] or r["bits"] is None:
            skipped += r["params"]
            total_bits += r["params"] * 16  # left in the model dtype (bf16)
            continue
        by_bits[r["bits"]] += r["params"]
        kind = r["path"].split(".")[-1]
        by_kind[(kind, r["bits"])] += r["params"]
        total_bits += r["params"] * (r["bits"] + OVERHEAD_BITS_PER_GROUP / gs)
    return {
        "total_params": total_params,
        "unquantized_params": skipped,
        "by_bits": dict(sorted(by_bits.items())),
        "by_kind": {f"{k}@{b}bit": v for (k, b), v in sorted(by_kind.items())},
        "effective_bits_per_weight": total_bits / total_params if total_params else 0.0,
        "estimated_bytes": total_bits / 8,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True, help="any converted variant of the same architecture")
    ap.add_argument("--recipe", default="mixed_2_6")
    ap.add_argument("--group-size", type=int, default=64)
    ap.add_argument("--embed-bits", type=int, default=None,
                    help="override bits for embed_tokens / lm_head (what our custom predicate does)")
    ap.add_argument("--low-modules", default="gate_proj,up_proj")
    ap.add_argument("--low-layers", default="lowsens", choices=["lowsens", "all"])
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    if not Path(args.ref).exists():
        print(f"reference model {args.ref} not found", file=sys.stderr)
        return 1

    print(f"loading module tree from {args.ref}")
    model, _ = load(args.ref)

    plan = build_plan(model, args.recipe, args.group_size, args.embed_bits,
                      tuple(m.strip() for m in args.low_modules.split(",") if m.strip()),
                      args.low_layers)
    s = summarize(plan)

    print(f"\nrecipe: {args.recipe}  group_size={args.group_size}"
          + (f"  embed/lm_head override={args.embed_bits}bit" if args.embed_bits else ""))
    print(f"quantizable params: {s['total_params']:,}")
    if s["unquantized_params"]:
        print(f"left unquantized (shape not divisible by group_size): {s['unquantized_params']:,}")
    print("\nparams by bit width:")
    for bits, n in s["by_bits"].items():
        print(f"  {bits}-bit: {n:>15,}  ({100 * n / s['total_params']:5.2f}%)")
    print("\nparams by module kind:")
    for k, n in s["by_kind"].items():
        print(f"  {k:<22} {n:>15,}  ({100 * n / s['total_params']:5.2f}%)")

    # which layer indices get the high-bit treatment
    hi = max(s["by_bits"]) if s["by_bits"] else None
    hi_layers = sorted({
        int(r["path"].split(".")[2])
        for r in plan["rows"]
        if r.get("bits") == hi and ".layers." in r["path"] and r["path"].split(".")[2].isdigit()
    })
    print(f"\ntransformer layers containing {hi}-bit modules: {hi_layers}")
    print(f"  ({len(hi_layers)} of {len({int(r['path'].split('.')[2]) for r in plan['rows'] if '.layers.' in r['path'] and r['path'].split('.')[2].isdigit()})})")

    print(f"\neffective bits/weight (incl. {OVERHEAD_BITS_PER_GROUP}b scale+bias per {args.group_size} weights):"
          f"  {s['effective_bits_per_weight']:.3f}")
    print(f"estimated weight size: {s['estimated_bytes'] / 2**30:.2f} GiB "
          f"({s['estimated_bytes'] / 1e9:.2f} GB)")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"plan": plan, "summary": s}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
