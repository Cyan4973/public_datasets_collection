#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/evaluation/aras_blender_openexr_eval"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="aras_blender_openexr_eval"
EVAL_ROOT="$REPO_ROOT/$DATA_DIR/evaluation/$DATASET_ID"
DOWNLOAD_DIR="$EVAL_ROOT/downloads"
TOOL_DIR="$EVAL_ROOT/tools/tinyexr_v1.0.12"
LOG_DIR="$EVAL_ROOT/logs"
DECODER="$TOOL_DIR/openzl_aras_exr_verify"

mkdir -p "$LOG_DIR" "$TOOL_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] evaluation verify start dataset=$DATASET_ID"

VERIFY_ROOT="$(mktemp -d "$EVAL_ROOT/verify_tmp.XXXXXX")"
cleanup() { rm -rf -- "$VERIFY_ROOT"; }
trap cleanup EXIT
mkdir -p "$VERIFY_ROOT/filtered" \
  "$VERIFY_ROOT/samples/blender_exr_channel_plane_f16" \
  "$VERIFY_ROOT/samples/blender_exr_channel_plane_f32"

c++ -std=c++11 -O2 -Wall -Wextra -pedantic \
  -DTINYEXR_USE_MINIZ=0 -I"$TOOL_DIR" \
  "$RECIPE_DIR/scripts/exr_decode.cpp" -lz -o "$DECODER.part"
mv "$DECODER.part" "$DECODER"

while IFS=$'\t' read -r kind name _rest; do
  [[ "$kind" == "kind" ]] && continue
  [[ "$kind" == "exr" ]] || continue
  stem="${name%.exr}"
  "$DECODER" "$DOWNLOAD_DIR/$name" "$VERIFY_ROOT/samples" \
    "$VERIFY_ROOT/filtered/decode_$stem.tsv"
done < "$RECIPE_DIR/selection.tsv"

python3 "$RECIPE_DIR/scripts/verify.py" \
  --selection "$RECIPE_DIR/selection.tsv" \
  --eval-root "$EVAL_ROOT" \
  --fresh-root "$VERIFY_ROOT"

echo "[$(date -Is)] evaluation verify done dataset=$DATASET_ID"
