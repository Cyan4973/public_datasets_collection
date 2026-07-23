#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bbbc039_microscopy_tiff_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
URL_LIST="${BBBC039_URLS_FILE:-$REPO_ROOT/datasets/$DATASET_ID/urls.txt}"
python3 "$REPO_ROOT/tools/bounded_url_download.py" \
  --dataset-id "$DATASET_ID" \
  --download-dir "$DOWNLOAD_DIR" \
  --url-list "$URL_LIST" \
  --seed-url "https://data.broadinstitute.org/bbbc/BBBC039/" \
  --suffix .tif --suffix .tiff --suffix .zip \
  --max-files "${MAX_FILES:-5}" \
  --max-file-bytes "${MAX_FILE_BYTES:-1200000000}" \
  --max-total-bytes "${MAX_DOWNLOAD_BYTES:-1200000000}"
