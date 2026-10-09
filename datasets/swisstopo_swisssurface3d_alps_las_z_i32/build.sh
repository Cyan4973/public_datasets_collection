#!/usr/bin/env bash
# Stream each pinned local zip's LAS member (no extraction to disk) and emit the
# full Z column of every tile as raw little-endian int32, one sample per tile.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="swisstopo_swisssurface3d_alps_las_z_i32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/las_z.py" self-test
python3 -I "$RECIPE_DIR/scripts/las_z.py" build \
  --sources "$RECIPE_DIR/sources.tsv" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID/zip" \
  --data-root "$DATA_ROOT"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
