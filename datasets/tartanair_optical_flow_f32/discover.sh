#!/usr/bin/env bash
# Documents how sources.tsv was resolved: list the pinned Hugging Face
# revision of theairlabcmu/tartanair (one small API page) and regenerate the
# 36 flow_flow.zip rows (path, size, LFS sha256, xet hash).  The result is
# written under $DATA_DIR/discovery/ and diffed against the committed
# sources.tsv; this script never edits the recipe.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tartanair_optical_flow_f32"
REVISION="65e00180ea952475878a748543e11e9ec20beaac"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/tartanair_flow.py"
UA="openzl-public-datasets-tartanair-flow/1.0"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID revision=$REVISION"

curl --fail --silent --show-error --location --globoff --max-time 120 \
  --retry 5 --retry-delay 5 --retry-all-errors --user-agent "$UA" \
  --output "$OUT_DIR/tree.json" \
  "https://huggingface.co/api/datasets/theairlabcmu/tartanair/tree/$REVISION?recursive=true"
python3 "$PY" sources-from-tree --tree "$OUT_DIR/tree.json" > "$OUT_DIR/sources.generated.tsv"
if diff -u "$RECIPE_DIR/sources.tsv" "$OUT_DIR/sources.generated.tsv"; then
  echo "sources.tsv matches the pinned revision listing ($(($(wc -l < "$OUT_DIR/sources.generated.tsv") - 1)) archives)"
else
  echo "sources.tsv differs from the pinned revision listing" >&2
  exit 1
fi
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
