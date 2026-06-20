#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="binance_usdm_futures_bookticker_2024_w01"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
# Multi-symbol week of full daily bookTicker ZIPs is several GB; raise the source-byte cap.
export MAX_SOURCE_BYTES="${MAX_SOURCE_BYTES:-6000000000}"
export REPO_ROOT DATA_DIR
echo "[$(date -Is)] download start dataset=$DATASET_ID max_source_bytes=$MAX_SOURCE_BYTES"
python3 "$REPO_ROOT/tools/binance_archive_recipe.py" download "$REPO_ROOT/datasets/$DATASET_ID/config.json"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
