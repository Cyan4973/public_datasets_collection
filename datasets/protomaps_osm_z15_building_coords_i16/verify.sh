#!/usr/bin/env bash
# Re-derive every sample from the downloaded archive pieces and check bytes,
# index fields, ranges, non-degeneracy, floors, and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="protomaps_osm_z15_building_coords_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/pmtiles_mvt.py"
python3 -I "$RECIPE_DIR/scripts/recipe.py" verify --recipe-dir "$RECIPE_DIR" --data-root "$DATA_ROOT"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
