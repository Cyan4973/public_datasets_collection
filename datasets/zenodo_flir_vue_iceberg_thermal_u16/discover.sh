#!/usr/bin/env bash
# Optional: re-derive scripts/frames.tsv (how the pinned selection was resolved on 2026-10-08).
# Not part of the download contract. Metadata requests only: the Zenodo record JSON and a
# 256 KiB tail range of each of the six zips (EOCD + central directory). Also proves that
# 20180821_160000.zip is a byte-identical subset of 20180821_155204.zip.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_flir_vue_iceberg_thermal_u16"
WORK="${DISCOVER_DIR:-$DATA_ROOT/filtered/$DATASET_ID/discover}"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$WORK/tails" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1

curl -fsS --retry 5 --max-time 120 -o "$WORK/record.json" "https://zenodo.org/api/records/10641368"
python3 -I "$RECIPE_DIR/scripts/discover.py" sessions | while read -r name size; do
  curl -fsSL --retry 5 --max-time 300 -r -262144 -o "$WORK/tails/$name.tail" \
    "https://zenodo.org/records/10641368/files/$name?download=1"
  echo "$name tail $(stat -c %s "$WORK/tails/$name.tail") bytes (zip size pinned $size)"
done
python3 -I "$RECIPE_DIR/scripts/discover.py" table --tails "$WORK/tails" > "$WORK/frames.tsv"
if cmp -s "$WORK/frames.tsv" "$RECIPE_DIR/scripts/frames.tsv"; then
  echo "discovery reproduces the pinned table"
else
  echo "discovery differs from the pinned table (upstream drift):"
  diff "$RECIPE_DIR/scripts/frames.tsv" "$WORK/frames.tsv" | head -40 || true
fi
