#!/usr/bin/env bash
# Local-only build: decode the 12 pinned COPC tiles with tools/laz/laszip.py
# and emit one raw little-endian uint16 Intensity array per tile (stored COPC
# octree-node order). Tiles are decoded in parallel (JOBS, default auto).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ROOT="$DATA_DIR" ;; *) ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ign_lidarhd_terrainmapper_intensity_u16"
LOG_DIR="$ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/ign_intensity.py" build \
  --sources "$RECIPE_DIR/sources.tsv" \
  --data-root "$ROOT" \
  --laz-dir "$REPO_ROOT/tools/laz" \
  --jobs "${JOBS:-0}"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
