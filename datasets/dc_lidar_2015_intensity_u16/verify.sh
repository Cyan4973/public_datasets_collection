#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/dc_lidar_2015_intensity_u16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dc_lidar_2015_intensity_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/las_intensity.py" verify \
  --download-dir "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/las" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --data-root "$REPO_ROOT/$DATA_DIR"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
