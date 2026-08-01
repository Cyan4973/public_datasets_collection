#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/openneuro_ds000030_t1w_mri_f32"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openneuro_ds000030_t1w_mri_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/nifti_float32.py" build \
  --download-dir "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID" \
  --samples-dir "$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
