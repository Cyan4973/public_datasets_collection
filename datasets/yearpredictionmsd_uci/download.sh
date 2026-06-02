#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="yearpredictionmsd_uci"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"
URLS=(
  "https://archive.ics.uci.edu/static/public/203/yearpredictionmsd.zip"
  "https://archive.ics.uci.edu/static/public/203/YearPredictionMSD.zip"
  "https://archive.ics.uci.edu/ml/machine-learning-databases/00203/YearPredictionMSD.txt.zip"
)
ARCHIVE=""
for url in "${URLS[@]}"; do
  out="$DOWNLOAD_DIR/$(basename "$url")"
  if curl -fL --retry 3 --retry-delay 2 -o "$out" "$url"; then
    ARCHIVE="$out"
    break
  fi
done
test -n "$ARCHIVE"
unzip -o "$ARCHIVE" -d "$EXTRACT_DIR" >/dev/null
for z in "$EXTRACT_DIR"/*.zip; do
  [ -e "$z" ] || continue
  unzip -o "$z" -d "$EXTRACT_DIR" >/dev/null
done
for g in "$EXTRACT_DIR"/*.gz; do
  [ -e "$g" ] || continue
  gunzip -fk "$g"
done
test -f "$EXTRACT_DIR/YearPredictionMSD.txt"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
