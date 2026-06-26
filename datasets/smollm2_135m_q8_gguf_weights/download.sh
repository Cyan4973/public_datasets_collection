#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="smollm2_135m_q8_gguf_weights"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

UA="${HF_UA:-openzl-public-datasets/1.0}"
URL="${GGUF_URL:-https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q8_0.gguf}"
OUT="$DOWNLOAD_DIR/model.gguf"

echo "[$(date -Is)] download start dataset=$DATASET_ID url=$URL"

if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && head -c4 "$OUT" | grep -q 'GGUF'; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT bytes=$(wc -c < "$OUT")"
else
  # Resumable, stall-based (no hard --max-time): survives slow CDN without restarting.
  curl -fL -C - -A "$UA" --retry 10 --retry-delay 5 \
       --speed-limit 1024 --speed-time 120 -o "$OUT" "$URL"
  # Validate it is really a GGUF container.
  if ! head -c4 "$OUT" | grep -q 'GGUF'; then
    echo "ERROR: downloaded file is not a GGUF (bad magic)" >&2
    exit 1
  fi
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$(wc -c < "$OUT")"
