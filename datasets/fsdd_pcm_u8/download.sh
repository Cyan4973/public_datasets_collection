#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="fsdd_pcm_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
ARCHIVE="$DOWNLOAD_DIR/fsdd_master.zip"
URL="${FSDD_URL:-https://github.com/Jakobovski/free-spoken-digit-dataset/archive/refs/heads/master.zip}"
if [ -s "$ARCHIVE" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit archive=$ARCHIVE"
else
  curl -fL -C - --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 -o "$ARCHIVE" "$URL"
fi
unzip -o "$ARCHIVE" -d "$EXTRACT_DIR" >/dev/null
test -d "$EXTRACT_DIR/free-spoken-digit-dataset-master/recordings"
echo "[$(date -Is)] download done dataset=$DATASET_ID recordings=$(ls "$EXTRACT_DIR/free-spoken-digit-dataset-master/recordings" | wc -l)"
