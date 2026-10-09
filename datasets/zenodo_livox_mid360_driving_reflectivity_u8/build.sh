#!/usr/bin/env bash
# Build one uint8 reflectivity sample per /livox/lidar PointCloud2 frame (2,772 frames).
# Uses only $DATA_DIR/downloads/zenodo_livox_mid360_driving_reflectivity_u8/. Needs about
# 1.5 GB of temporary space under $DATA_DIR/extracted/<id>/ for the SQLite member; the
# extract is deleted when the build finishes (also on failure).
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_livox_mid360_driving_reflectivity_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/livox_bag.py" self-test
python3 -I "$RECIPE_DIR/scripts/build_samples.py" --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
