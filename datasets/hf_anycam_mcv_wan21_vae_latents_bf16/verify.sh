#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ;; *) DATA_DIR="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hf_anycam_mcv_wan21_vae_latents_bf16"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$DATA_DIR/samples/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
# Independent path: each archive is reassembled sparsely from its fragments and read with the
# standard-library zipfile module (CRC-checked), then compared to the built samples and index.
python3 -I "$RECIPE_DIR/scripts/anycam_latents.py" verify \
  --download-dir "$DOWNLOAD_DIR" \
  --samples-dir "$SAMPLES_DIR" \
  --index "$INDEX_DIR/samples.jsonl" \
  --stats "$FILTER_DIR/ingest_stats.json" \
  --scratch "$FILTER_DIR/verify_scratch"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
