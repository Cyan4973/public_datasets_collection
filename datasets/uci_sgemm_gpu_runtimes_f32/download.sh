#!/usr/bin/env bash
# Acquire and preflight the official UCI SGEMM benchmark source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_sgemm_gpu_runtimes_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
ARCHIVE="$DOWNLOAD_DIR/sgemm_gpu_kernel_performance.zip"
METADATA="$DOWNLOAD_DIR/uci_dataset_440.json"
RIGHTS="$DOWNLOAD_DIR/uci_dataset_440.html"

mkdir -p "$DOWNLOAD_DIR" "$DISCOVERY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch_if_needed() {
  local target="$1" url="$2" max_bytes="$3"
  if [[ -f "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "reuse existing $(basename "$target") bytes=$(stat -c %s "$target")"
    return
  fi
  local part="$target.part"
  rm -f "$part"
  curl --globoff --fail-with-body --silent --show-error --location \
    --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
    --max-time 1800 --max-filesize "$max_bytes" \
    --user-agent "openzl-public-datasets/1.0" --output "$part" "$url"
  [[ -s "$part" ]] || { echo "empty response for $url" >&2; exit 1; }
  mv "$part" "$target"
}

fetch_if_needed "$METADATA" "https://archive.ics.uci.edu/api/dataset?id=440" 2000000
fetch_if_needed "$RIGHTS" "https://archive.ics.uci.edu/dataset/440/sgemm+gpu+kernel+performance" 5000000
fetch_if_needed "$ARCHIVE" "https://archive.ics.uci.edu/static/public/440/sgemm+gpu+kernel+performance.zip" 200000000

python3 "$RECIPE_DIR/scripts/sgemm.py" preflight \
  --archive "$ARCHIVE" --metadata "$METADATA" --rights "$RIGHTS" \
  --profile "$DISCOVERY_DIR/source_profile.json"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
