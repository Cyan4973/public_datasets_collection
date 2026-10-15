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
mkdir -p "$FILTER_DIR" "$INDEX_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/anycam_latents.py" build \
  --download-dir "$DOWNLOAD_DIR" \
  --samples-dir "$SAMPLES_DIR" \
  --index "$INDEX_DIR/samples.jsonl" \
  --stats "$FILTER_DIR/ingest_stats.json"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
