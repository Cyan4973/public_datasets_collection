#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_powder_xrd_patterns_f32"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

RECORD_URL="https://zenodo.org/api/records/4955141"
ARCHIVE_URL="https://zenodo.org/api/records/4955141/files/Cubic%20High-Pressure%20Repository.zip/content"
RECORD_FILE="$DOWNLOAD_DIR/record.json"
ARCHIVE_FILE="$DOWNLOAD_DIR/Cubic_High-Pressure_Repository.zip"

fetch() {
  local url="$1"
  local target="$2"
  local cap="$3"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit path=$target"
    return
  fi
  curl --fail-with-body --silent --show-error --location \
    --retry 4 --retry-delay 3 --max-time 900 --max-filesize "$cap" \
    --user-agent "openzl-public-datasets-powder-xrd-f32/1.0" \
    --output "$target.part" "$url"
  mv "$target.part" "$target"
}

fetch "$RECORD_URL" "$RECORD_FILE" 5000000
fetch "$ARCHIVE_URL" "$ARCHIVE_FILE" 100000000
python3 "$RECIPE_DIR/scripts/xrd.py" validate-download \
  --record "$RECORD_FILE" --archive "$ARCHIVE_FILE"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
