#!/usr/bin/env bash
# Decode the buildings layer of every pinned z15 tile from local span files and
# emit one little-endian int16 interleaved x/y vertex sample per tile.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="protomaps_osm_z15_building_coords_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/pmtiles_mvt.py"
python3 -I "$RECIPE_DIR/scripts/recipe.py" build --recipe-dir "$RECIPE_DIR" --data-root "$DATA_ROOT"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
