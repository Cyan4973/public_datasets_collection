#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="susy_uci"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"
ARCHIVE="$DOWNLOAD_DIR/susy.zip"
curl -fL --retry 3 --retry-delay 2 -o "$ARCHIVE" https://archive.ics.uci.edu/static/public/279/susy.zip
unzip -o "$ARCHIVE" -d "$EXTRACT_DIR" >/dev/null
for g in "$EXTRACT_DIR"/*.gz; do
  [ -e "$g" ] || continue
  gunzip -fk "$g"
done
test -f "$EXTRACT_DIR/SUSY.csv.gz" -o -f "$EXTRACT_DIR/SUSY.csv"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
