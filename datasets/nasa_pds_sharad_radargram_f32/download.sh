#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_sharad_radargram_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 "$REPO_ROOT/tools/bounded_url_download.py" \
  --dataset-id "$DATASET_ID" \
  --download-dir "$DOWNLOAD_DIR" \
  --url-list "${SHARAD_URLS_FILE:-$REPO_ROOT/datasets/$DATASET_ID/urls.txt}" \
  --suffix .lbl \
  --suffix .img \
  --max-files "${MAX_FILES:-20}" \
  --max-total-bytes "${MAX_DOWNLOAD_BYTES:-1000000000}"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
