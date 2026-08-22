#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_heasarc_nicer_detector_u8"
SOURCE_DATASET_ID="nasa_heasarc_nicer_pi_i16"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
SOURCE_RECIPE="$REPO_ROOT/datasets/$SOURCE_DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/nicer_detector.py" build \
  --sources "$SOURCE_RECIPE/sources.tsv" \
  --download-dir "$REPO_ROOT/$DATA_DIR/downloads/$SOURCE_DATASET_ID" \
  --samples-dir "$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
