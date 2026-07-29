#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dc_lidar_2015_gps_time_f64"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/las"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
INDEX_FILE="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl"
STATS_FILE="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$REPO_ROOT/datasets/$DATASET_ID/scripts/las_gps_time.py" build \
  --download-dir "$DOWNLOAD_DIR" --samples-dir "$SAMPLES_DIR" \
  --index "$INDEX_FILE" --stats "$STATS_FILE"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
