#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="polyhaven_hdri_exr_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
# Reuse f16 downloads if present to avoid re-download: copy any existing 1k exr from f16 dir
SRC_F16_DIR="$REPO_ROOT/$DATA_DIR/downloads/polyhaven_hdri_exr_f16"
if [ -d "$SRC_F16_DIR" ]; then
  echo "copying existing f16 exr assets as f32 source for reclassification"
  cp -n "$SRC_F16_DIR"/*.exr "$DOWNLOAD_DIR"/ 2>/dev/null || true
fi
python3 "$REPO_ROOT/tools/bounded_url_download.py" \
  --dataset-id "$DATASET_ID" \
  --download-dir "$DOWNLOAD_DIR" \
  --mode polyhaven \
  --max-files "${ASSET_LIMIT:-12}" \
  --max-total-bytes "${MAX_DOWNLOAD_BYTES:-1000000000}"
