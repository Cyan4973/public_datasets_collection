#!/usr/bin/env bash
# Optional: re-derive scripts/assets.tsv (how the pinned selection was resolved on 2026-10-08).
# Not part of the download contract. Small metadata requests only: 5 API pages (~25 MB JSON),
# a 16 KiB tail range of each 1K-PNG zip (central directory), and a ~600-byte range at
# each NormalGL member's local header (PNG IHDR). Output: $WORK/assets.tsv (diff against the pin).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ambientcg_photogrammetry_normalgl_u16"
WORK="${DISCOVER_DIR:-$DATA_ROOT/filtered/$DATASET_ID/discover}"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$WORK/tails" "$WORK/heads" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
API="https://ambientcg.com/api/v2/full_json?type=Material&sort=Alphabet&limit=500&include=downloadData"

for offset in 0 500 1000 1500 2000; do
  curl -fsS --retry 5 --max-time 300 -o "$WORK/api_page_$offset.json" "$API&offset=$offset"
done
python3 -I "$RECIPE_DIR/scripts/discover.py" assets --work "$WORK" | while read -r asset size; do
  curl -fsSL --retry 5 --max-time 120 -r -16384 -o "$WORK/tails/$asset.tail" \
    "https://ambientcg.com/get?file=${asset}_1K-PNG.zip"
done
python3 -I "$RECIPE_DIR/scripts/discover.py" heads --work "$WORK" | while read -r asset start end; do
  curl -fsSL --retry 5 --max-time 120 -r "$start-$end" -o "$WORK/heads/$asset.head" \
    "https://ambientcg.com/get?file=${asset}_1K-PNG.zip"
done
python3 -I "$RECIPE_DIR/scripts/discover.py" table --work "$WORK" > "$WORK/assets.tsv"
if cmp -s "$WORK/assets.tsv" "$RECIPE_DIR/scripts/assets.tsv"; then
  echo "discovery reproduces the pinned table"
else
  echo "discovery differs from the pinned table (upstream drift):"
  diff "$RECIPE_DIR/scripts/assets.tsv" "$WORK/assets.tsv" | head -40 || true
fi
