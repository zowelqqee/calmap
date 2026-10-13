#!/usr/bin/env bash
# Build every precision variant from ONE upstream checkpoint with mlx_lm.convert.
#
#   ./quantize_models.sh              # build 8, 6, 4, 3 bit
#   ./quantize_models.sh 4 3          # build only 4-bit and 3-bit
#   SOURCE_MODEL=Qwen/Qwen3-4B-Instruct-2507 ./quantize_models.sh
#
# Notes / real MLX limits (checked against mlx 0.32.0 / mlx-lm 0.31.3):
#   * affine quantization supports bits in {2,3,4,5,6,8}. 7-bit does not exist.
#   * a layer is left unquantized when its last dim is not divisible by
#     --q-group-size; mlx-lm prints the resulting bits-per-weight.
#   * mlx_lm.convert also has --q-mode {affine,mxfp4,nvfp4,mxfp8} and
#     --quant-predicate {mixed_2_6,mixed_3_4,mixed_3_6,mixed_4_6}. We stay on
#     uniform affine so bit-width is the only variable across variants.

set -euo pipefail

SOURCE_MODEL="${SOURCE_MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
OUT_PREFIX="${OUT_PREFIX:-models/qwen3-4b-instruct-2507}"
GROUP_SIZE="${GROUP_SIZE:-64}"
QUANT_MODE="${QUANT_MODE:-affine}"
# Optional: pin an upstream revision for full reproducibility, e.g.
#   REVISION=main ./quantize_models.sh
REVISION="${REVISION:-}"

cd "$(dirname "$0")"

if ! command -v mlx_lm.convert >/dev/null 2>&1; then
  echo "mlx_lm.convert not found. Activate the venv first:" >&2
  echo "  source .venv/bin/activate" >&2
  exit 1
fi

BITS=("$@")
if [ ${#BITS[@]} -eq 0 ]; then
  BITS=(8 6 4 3)
fi

echo "source model : $SOURCE_MODEL"
echo "quant mode   : $QUANT_MODE (group size $GROUP_SIZE)"
echo "bit widths   : ${BITS[*]}"
echo "free disk    : $(df -h . | tail -1 | awk '{print $4}')"
echo

for b in "${BITS[@]}"; do
  case "$b" in
    2|3|4|5|6|8) ;;
    *) echo "!! affine quantization does not support ${b}-bit, skipping" >&2; continue ;;
  esac

  out="${OUT_PREFIX}-q${b}"
  if [ -d "$out" ]; then
    echo "== q${b}: $out already exists, skipping"
    continue
  fi

  echo "== q${b}: converting -> $out"
  args=(--hf-path "$SOURCE_MODEL"
        --mlx-path "$out"
        -q
        --q-bits "$b"
        --q-group-size "$GROUP_SIZE"
        --q-mode "$QUANT_MODE")
  if [ -n "$REVISION" ]; then
    args+=(--revision "$REVISION")
  fi

  mlx_lm.convert "${args[@]}"
  du -sh "$out"
  echo
done

echo "done. variants on disk:"
du -sh "${OUT_PREFIX}"-q* 2>/dev/null || true
echo
echo "The upstream bf16 checkpoint stays in the HuggingFace cache (~8 GB)."
echo "Once every variant is built you can reclaim that space with:"
echo "  huggingface-cli delete-cache        # interactive"
echo "  # or: rm -rf ~/.cache/huggingface/hub/models--Qwen--Qwen3-4B-Instruct-2507"
