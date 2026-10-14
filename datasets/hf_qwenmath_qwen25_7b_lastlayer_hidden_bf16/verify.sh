#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hf_qwenmath_qwen25_7b_lastlayer_hidden_bf16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
FILTER_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
SAMPLES_DIR="$DATA_ROOT/samples/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$FILTER_DIR" "$INDEX_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/qwenmath_hidden.py" verify \
  --download-dir "$DOWNLOAD_DIR" \
  --samples-dir "$SAMPLES_DIR" \
  --index "$INDEX_DIR/samples.jsonl" \
  --stats "$FILTER_DIR/ingest_stats.json" \
  --manifest "$RECIPE_DIR/manifest.toml"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
