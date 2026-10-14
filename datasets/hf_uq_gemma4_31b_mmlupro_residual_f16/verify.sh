#!/usr/bin/env bash
# Run the "verify" step for the uq-hiddenstates Gemma-4-31B-it L45 MMLU-Pro samples (local files only).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ;; *) DATA_DIR="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hf_uq_gemma4_31b_mmlupro_residual_f16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$DATA_DIR/samples/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/uq_hidden.py" verify \
  --download-dir "$DOWNLOAD_DIR" \
  --data-dir "$DATA_DIR" \
  --samples-dir "$SAMPLES_DIR" \
  --index "$INDEX_DIR/samples.jsonl" \
  --stats "$FILTER_DIR/ingest_stats.json"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
