#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_geomag_observatory_minute_f32"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$FILTER_DIR" "$INDEX_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/geomag.py" build \
  --download-dir "$DOWNLOAD_DIR" \
  --samples-dir "$SAMPLES_DIR" \
  --index "$INDEX_DIR/samples.jsonl" \
  --stats "$FILTER_DIR/ingest_stats.json"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
