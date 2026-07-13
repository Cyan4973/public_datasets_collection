#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="fmnist_px_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

UA="${FMNIST_UA:-openzl-public-datasets/1.0}"
BASE="${FMNIST_BASE:-https://github.com/zalandoresearch/fashion-mnist/raw/master/data/fashion}"
FILES=(train-images-idx3-ubyte.gz train-labels-idx1-ubyte.gz t10k-images-idx3-ubyte.gz t10k-labels-idx1-ubyte.gz)

echo "[$(date -Is)] download start dataset=$DATASET_ID base=$BASE"
for f in "${FILES[@]}"; do
  out="$DOWNLOAD_DIR/$f"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit $f"
  else
    curl -fL -C - -A "$UA" --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 -o "$out" "$BASE/$f"
  fi
  # gzip magic check
  if [ "$(head -c2 "$out" | xxd -p)" != "1f8b" ]; then
    echo "ERROR: $f is not gzip" >&2; exit 1
  fi
done
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$(ls "$DOWNLOAD_DIR" | wc -l)"
