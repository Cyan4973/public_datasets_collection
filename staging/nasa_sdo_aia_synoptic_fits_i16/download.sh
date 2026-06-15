#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_sdo_aia_synoptic_fits_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
FILE_LIMIT="${FILE_LIMIT:-8}"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-500000000}"
"$REPO_ROOT/tools/catalog_package_download.py" \
  --dataset-id "$DATASET_ID" \
  --package-id "sdo-aia-synoptic-fits-data" \
  --download-dir "$DOWNLOAD_DIR" \
  --pattern 'fits|fit|\.fits(\.gz)?$|\.fit(\.gz)?$|\.zip$|\.tar(\.gz)?$' \
  --file-limit "$FILE_LIMIT" \
  --min-files 1 \
  --max-file-bytes "$MAX_FILE_BYTES" \
  --min-file-bytes 10240
echo "[$(date -Is)] download done dataset=$DATASET_ID"
