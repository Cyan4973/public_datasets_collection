#!/usr/bin/env bash
# Acquire and preflight the official UCI Parking Birmingham source.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_parking_birmingham_occupancy_i16"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
ARCHIVE="$DOWNLOAD_DIR/parking_birmingham.zip"
METADATA="$DOWNLOAD_DIR/uci_dataset_482.json"
RIGHTS="$DOWNLOAD_DIR/uci_dataset_482.html"

mkdir -p "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$DISCOVERY_DIR" "$LOG_DIR"
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
    --max-time 600 --max-filesize "$max_bytes" \
    --user-agent "openzl-public-datasets/1.0" --output "$part" "$url"
  [[ -s "$part" ]] || { echo "empty response for $url" >&2; exit 1; }
  mv "$part" "$target"
}

fetch_if_needed "$METADATA" "https://archive.ics.uci.edu/api/dataset?id=482" 2000000
fetch_if_needed "$RIGHTS" "https://archive.ics.uci.edu/dataset/482/parking+birmingham" 5000000
fetch_if_needed "$ARCHIVE" "https://archive.ics.uci.edu/static/public/482/parking+birmingham.zip" 50000000

python3 "$RECIPE_DIR/scripts/parking.py" preflight \
  --archive "$ARCHIVE" --metadata "$METADATA" --rights "$RIGHTS" \
  --extracted "$EXTRACT_DIR/parking_birmingham.csv" \
  --profile "$DISCOVERY_DIR/source_profile.json"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
