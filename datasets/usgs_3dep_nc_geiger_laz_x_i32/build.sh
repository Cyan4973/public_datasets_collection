#!/usr/bin/env bash
# Build one little-endian int32 X sample per pinned Geiger-mode LAZ tile.
# Uses only files already under $DATA_DIR/downloads/usgs_3dep_nc_geiger_laz_x_i32/.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="usgs_3dep_nc_geiger_laz_x_i32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/geiger_tiles.py" self-test
python3 "$RECIPE_DIR/scripts/geiger_tiles.py" check-all --sources "$RECIPE_DIR/sources.tsv" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID"
python3 "$RECIPE_DIR/scripts/build_samples.py" --data-root "$DATA_ROOT" --sources "$RECIPE_DIR/sources.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
