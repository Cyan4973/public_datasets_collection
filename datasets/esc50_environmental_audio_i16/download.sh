#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="esc50_environmental_audio_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start $DATASET_ID"
URL="https://github.com/karoldvl/ESC-50/archive/master.zip"
OUT="$DOWNLOAD_DIR/ESC-50-master.zip"
if [ -f "$OUT" ]; then
  echo "using existing $OUT"
else
  curl -fL --retry 3 --retry-delay 5 -o "$OUT" "$URL"
fi
echo "downloaded $OUT $(stat -c%s "$OUT") bytes"
