#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
[[ "$DATA_DIR" = /* ]] || DATA_DIR="$REPO_ROOT/$DATA_DIR"
DATASET_ID="hf_tdig_evo2_7b_hg38_final_norm_hidden_f16"
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$DATA_DIR/samples/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTER_DIR" "$INDEX_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/tdig_evo2.py" build \
  --data-dir "$DATA_DIR" \
  --download-dir "$DOWNLOAD_DIR" \
  --samples-dir "$SAMPLES_DIR" \
  --index "$INDEX_DIR/samples.jsonl" \
  --stats "$FILTER_DIR/ingest_stats.json"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
