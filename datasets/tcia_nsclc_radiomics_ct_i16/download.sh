#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tcia_nsclc_radiomics_ct_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
python3 "$REPO_ROOT/tools/bounded_url_download.py" \
  --dataset-id "$DATASET_ID" \
  --download-dir "$DOWNLOAD_DIR" \
  --mode tcia_series \
  --tcia-collection "${TCIA_COLLECTION:-NSCLC-Radiomics}" \
  --max-files "${SERIES_LIMIT:-6}" \
  --max-total-bytes "${MAX_DOWNLOAD_BYTES:-1000000000}"
