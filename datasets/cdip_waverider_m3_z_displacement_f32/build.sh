#!/usr/bin/env bash
# Decode the downloaded OPeNDAP windows (local files only) and emit one raw
# little-endian float32 heave sample per DWR-M3 deployment window.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="cdip_waverider_m3_z_displacement_f32"
SERIES_ID="cdip_dwr_m3_heave_z_displacement_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/cdip_dods.py"
python3 -I "$RECIPE_DIR/scripts/cdip_m3.py" build \
  --windows "$RECIPE_DIR/windows.tsv" \
  --downloads "$DATA_ROOT/downloads/$DATASET_ID" \
  --data-root "$DATA_ROOT" \
  --dataset-id "$DATASET_ID" \
  --series-id "$SERIES_ID"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
