#!/usr/bin/env bash
# Decode the pinned 4P magnetic channel epochs (local files only) into
# gap-split little-endian int32 samples plus the sample index.
set -euo pipefail

DATASET_ID="earthscope_4p_mt_magnetic_field_counts_i32"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DL_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/mt_mseed.py" selftest
python3 -I "$RECIPE_DIR/scripts/mt_mseed.py" build \
  --selection "$RECIPE_DIR/selection.tsv" \
  --station-dir "$DL_DIR/station" \
  --downloads "$DL_DIR/mseed" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
