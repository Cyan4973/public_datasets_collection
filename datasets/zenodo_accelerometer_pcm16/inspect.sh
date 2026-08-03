#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/zenodo_accelerometer_pcm16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_accelerometer_pcm16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
REPORT="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/preflight.json"
mkdir -p "$LOG_DIR" "$(dirname "$REPORT")"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/inspect.$RUN_TS.log" "$LOG_DIR/inspect.latest.log") 2>&1
echo "[$(date -Is)] inspect start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/honeybee_accelerometer.py" inspect \
  --download-dir "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID" \
  --report "$REPORT"
echo "[$(date -Is)] inspect done dataset=$DATASET_ID"
