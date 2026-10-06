#!/usr/bin/env bash
# Build N x 3 little-endian float32 xyz samples, one per pinned GOOSE VLS-128 sweep.
# Uses only files already under $DATA_DIR/downloads/goose_vls128_lidar_scan_xyz_f32/.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="goose_vls128_lidar_scan_xyz_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/goose_zip.py" check-payloads --sources "$RECIPE_DIR/sources.tsv" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" --strict
python3 "$RECIPE_DIR/scripts/build_samples.py" --data-root "$DATA_ROOT" --sources "$RECIPE_DIR/sources.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
