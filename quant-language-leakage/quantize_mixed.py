#!/usr/bin/env python3
"""Build a mixed-precision variant from the same upstream checkpoint, measure it, and
register it in models/config.json — no manual edits anywhere.

    # stock MLX recipe
    python quantize_mixed.py --recipe mixed_2_6

    # stock recipe + tied embedding / output head kept at higher precision
    python quantize_mixed.py --recipe mixed_2_6 --embed-bits 6

The predicate itself always comes from the installed mlx-lm
(`mlx_lm.convert.mixed_quant_predicate_builder`). With --embed-bits we wrap that
predicate and override only `embed_tokens` / `lm_head`; nothing about the recipe's own
layer selection is reimplemented.

Building the wrapped predicate needs a module tree up front (MLX's builder inspects
`named_modules()` and `len(model.layers)`), and `convert()` only exposes the model after
it has loaded it. We therefore seed the builder from an already-converted variant of the
SAME architecture (--ref) and assert that its config matches the source model's. The
returned closure only ever looks at the module *path*, so this is exact.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import mlx.nn as nn
from mlx_lm.convert import QUANT_RECIPES, convert, mixed_quant_predicate_builder

DEFAULT_SOURCE = "Qwen/Qwen3-4B-Instruct-2507"


def dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


# Schemes beyond the four MLX ships. Built on top of MLX's own sensitivity classification
# (see low_sensitivity_layers below) — the layer selection is never reimplemented.
LOCAL_SCHEMES = {
    "mixed_3_2": (
        "3-bit floor (identical to uniform q3) except gate_proj and up_proj inside the "
        "layers MLX's own recipe classifies as low-sensitivity, which drop to 2-bit"
    ),
}


def load_reference(ref_path: Path, source_cfg: dict):
    from mlx_lm import load

    print(f"[plan] seeding MLX's predicate builder from reference module tree {ref_path}")
    ref_model, _ = load(str(ref_path))
    ref_cfg = json.loads((ref_path / "config.json").read_text(encoding="utf-8"))
    for key in ("model_type", "num_hidden_layers", "hidden_size", "intermediate_size",
                "num_attention_heads", "num_key_value_heads", "tie_word_embeddings"):
        if ref_cfg.get(key) != source_cfg.get(key):
            raise SystemExit(
                f"reference model does not match the source architecture on {key!r}: "
                f"{ref_cfg.get(key)!r} vs {source_cfg.get(key)!r}"
            )
    return ref_model


def low_sensitivity_layers(ref_model, group_size: int) -> list[int]:
    """Ask MLX which layers its mixed recipes treat as low-sensitivity.

    `mixed_quant_predicate_builder` hands back a closure that maps a module path to a bit
    width; for `mixed_2_6` a `down_proj` gets the high bits exactly when that layer is in
    the `use_more_bits` set. Querying that closure is how we reuse MLX's classification
    instead of re-deriving it. The closure ignores its `module` argument.
    """
    inner = mixed_quant_predicate_builder("mixed_2_6", ref_model, group_size)
    low = []
    for i in range(len(ref_model.layers)):
        params = inner(f"model.layers.{i}.mlp.down_proj", None)
        bits = params["bits"] if isinstance(params, dict) else None
        if bits == 2:  # low_bits for mixed_2_6 => this layer is NOT use_more_bits
            low.append(i)
    return low


def layer_index(path: str) -> int | None:
    parts = path.split(".")
    for p in parts:
        if p.isdigit():
            return int(p)
    return None


def predicate_from_model(scheme: str, ref_model, group_size: int, embed_bits: int | None,
                         low_bit_modules: tuple[str, ...] | None = None,
                         low_layer_scope: str = "lowsens"):
    """Build the callable predicate from an already-loaded module tree."""
    if scheme in QUANT_RECIPES:
        inner = mixed_quant_predicate_builder(scheme, ref_model, group_size)

        def predicate(path: str, module: nn.Module):
            if "embed_tokens" in path or "lm_head" in path:
                return {"group_size": group_size, "bits": embed_bits, "mode": "affine"}
            return inner(path, module)

        info = {"base_recipe": scheme, "embed_bits": embed_bits}

    elif scheme == "mixed_3_2":
        low_layers = set(low_sensitivity_layers(ref_model, group_size))
        head_bits = embed_bits or 3
        modules = list(low_bit_modules or ("gate_proj", "up_proj"))
        all_layers = low_layer_scope == "all"
        scope = set(range(len(ref_model.layers))) if all_layers else low_layers

        def predicate(path: str, module: nn.Module):
            bits = 3
            idx = layer_index(path)
            if idx in scope and any(m in path for m in modules):
                bits = 2
            if "embed_tokens" in path or "lm_head" in path:
                bits = head_bits
            return {"group_size": group_size, "bits": bits, "mode": "affine"}

        info = {"floor_bits": 3, "low_bits": 2,
                "low_bit_layer_scope": low_layer_scope,
                "low_sensitivity_layers": sorted(low_layers),
                "layers_at_low_bits": sorted(scope),
                "low_bit_modules": modules,
                "embed_bits": head_bits}
    else:
        raise SystemExit(f"unknown scheme {scheme!r}")

    return predicate, info


def build_predicate(scheme: str, ref_path: Path, group_size: int, embed_bits: int | None,
                    source_cfg: dict, low_bit_modules=None, low_layer_scope: str = "lowsens"):
    """Return either a stock recipe name (string, no reference model needed) or a callable."""
    if scheme in QUANT_RECIPES and embed_bits is None:
        return scheme, None
    ref_model = load_reference(ref_path, source_cfg)
    predicate, info = predicate_from_model(scheme, ref_model, group_size, embed_bits,
                                           low_bit_modules, low_layer_scope)
    del ref_model
    return predicate, info


def measure(out_path: Path) -> dict:
    """Load the converted model back and report what it actually is."""
    import mlx.core as mx
    from mlx_lm import load
    from mlx_lm.utils import compute_bits_per_weight

    model, _ = load(str(out_path))
    bpw = compute_bits_per_weight(model)

    by_bits: dict[int, int] = defaultdict(int)
    for _, module in model.named_modules():
        if isinstance(module, (nn.QuantizedLinear, nn.QuantizedEmbedding)):
            rows, packed = module.weight.shape
            by_bits[module.bits] += rows * packed * 32 // module.bits

    del model
    if hasattr(mx, "clear_cache"):
        mx.clear_cache()

    cfg = json.loads((out_path / "config.json").read_text(encoding="utf-8"))
    quant = cfg.get("quantization", {})
    per_layer = {k: v for k, v in quant.items() if isinstance(v, dict)}
    return {
        "effective_bits_per_weight": round(float(bpw), 4),
        "disk_bytes": dir_size_bytes(out_path),
        "params_by_bits": {str(k): v for k, v in sorted(by_bits.items())},
        "config_quantization_defaults": {k: v for k, v in quant.items() if not isinstance(v, dict)},
        "config_per_module_entries": len(per_layer),
    }


def register(config_path: Path, entry: dict) -> None:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg["variants"] = [v for v in cfg["variants"] if v["name"] != entry["name"]]
    cfg["variants"].append(entry)
    # keep the file ordered by decreasing precision so analyze.py's default baseline
    # (first entry) stays the highest-precision variant
    cfg["variants"].sort(key=lambda v: -(v.get("effective_bits_per_weight") or v.get("bits") or 0))
    config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recipe", default="mixed_2_6", choices=QUANT_RECIPES + list(LOCAL_SCHEMES),
                    help="stock MLX recipe, or a local scheme: "
                         + "; ".join(f"{k} = {v}" for k, v in LOCAL_SCHEMES.items()))
    ap.add_argument("--embed-bits", type=int, default=None,
                    help="override bits for the tied embedding / lm_head (2,3,4,5,6,8)")
    ap.add_argument("--low-modules", default="gate_proj,up_proj",
                    help="mixed_3_2 only: which module kinds drop to 2-bit")
    ap.add_argument("--low-layers", default="lowsens", choices=["lowsens", "all"],
                    help="mixed_3_2 only: apply the 2-bit drop to MLX's low-sensitivity "
                         "layers, or to every layer")
    ap.add_argument("--group-size", type=int, default=64)
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--ref", default="models/qwen3-4b-instruct-2507-q2",
                    help="converted variant of the same architecture, used to seed the predicate builder")
    ap.add_argument("--name", default=None, help="variant name (default derived from the recipe)")
    ap.add_argument("--out", default=None, help="output dir (default models/<source-slug>-<name>)")
    ap.add_argument("--config", default="models/config.json")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    args = ap.parse_args()

    if args.embed_bits is not None and args.embed_bits not in (2, 3, 4, 5, 6, 8):
        print("affine quantization supports bits in {2,3,4,5,6,8}", file=sys.stderr)
        return 1

    name = args.name or (args.recipe if args.embed_bits is None else f"{args.recipe}_emb{args.embed_bits}")
    out_path = Path(args.out or f"models/qwen3-4b-instruct-2507-{name}")
    config_path = Path(args.config)

    if out_path.exists():
        print(f"{out_path} already exists — delete it or pass --out", file=sys.stderr)
        return 1

    # the source config tells us the architecture; resolve it from the local HF cache so
    # this check never triggers an 8 GB download on its own
    from mlx_lm.utils import hf_repo_to_path, load_config
    src_dir = Path(args.source)
    if not src_dir.exists():
        try:
            src_dir = hf_repo_to_path(args.source)
        except Exception as exc:
            print(f"could not resolve {args.source} from the local HF cache ({exc}).\n"
                  f"Run ./quantize_models.sh once first, or pass a local --source.", file=sys.stderr)
            return 1
    source_cfg = load_config(src_dir)

    print(f"source     : {args.source}")
    print(f"recipe     : {args.recipe}" + (f" + embed/lm_head @ {args.embed_bits}bit" if args.embed_bits else ""))
    print(f"group size : {args.group_size}")
    print(f"output     : {out_path}")
    print(f"free disk  : {free_bytes(Path('.')) / 2**30:.1f} GiB")
    if source_cfg.get("tie_word_embeddings"):
        print("note       : tie_word_embeddings=true — there is no separate lm_head module, "
              "so the recipe's lm_head rule cannot fire; the tied embedding is the output head.")
    if args.dry_run:
        return 0

    predicate, scheme_info = build_predicate(
        args.recipe, Path(args.ref), args.group_size, args.embed_bits, source_cfg,
        tuple(m.strip() for m in args.low_modules.split(",") if m.strip()), args.low_layers
    )
    if scheme_info:
        print(f"scheme     : {json.dumps(scheme_info, ensure_ascii=False)}")

    convert(
        hf_path=args.source,
        mlx_path=str(out_path),
        quantize=True,
        q_group_size=args.group_size,   # always explicit: the builder is called with this value
        q_mode="affine",
        quant_predicate=predicate,
    )

    info = measure(out_path)
    entry = {
        "name": name,
        "path": str(out_path),
        "quantization": f"{args.recipe}-g{args.group_size}"
                        + (f"-emb{args.embed_bits}" if args.embed_bits else ""),
        "bits": None,
        "effective_bits_per_weight": info["effective_bits_per_weight"],
        "quant_mode": "affine",
        "group_size": args.group_size,
        "quant_predicate": args.recipe + (f"+embed{args.embed_bits}" if args.embed_bits else ""),
        "scheme_info": scheme_info,
        "baseline": False,
        "disk_gib": round(info["disk_bytes"] / 2**30, 3),
        "params_by_bits": info["params_by_bits"],
        "source_model": args.source,
    }

    print("\n--- measured ---")
    print(f"effective bits/weight (MLX compute_bits_per_weight): {info['effective_bits_per_weight']}")
    print(f"size on disk: {info['disk_bytes'] / 2**30:.2f} GiB ({info['disk_bytes'] / 1e9:.2f} GB)")
    print(f"quantization defaults in config.json: {info['config_quantization_defaults']}")
    print(f"per-module quantization entries in config.json: {info['config_per_module_entries']}")
    print("params by bit width:")
    total = sum(int(v) for v in info["params_by_bits"].values())
    for b, n in info["params_by_bits"].items():
        print(f"  {b}-bit: {n:>15,}  ({100 * n / total:5.2f}%)")

    register(config_path, entry)
    print(f"\nregistered variant {name!r} in {config_path}")
    print(f"next: python run_benchmark.py --variants {name} --max-prompts 2 --output results/raw.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
