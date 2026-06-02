#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="electricity_load_diagrams_uci"
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
  "https://archive.ics.uci.edu/static/public/321/electricityloaddiagrams20112014.zip"
  "https://archive.ics.uci.edu/static/public/321/ElectricityLoadDiagrams20112014.zip"
  "https://archive.ics.uci.edu/ml/machine-learning-databases/00321/ElectricityLoadDiagrams20112014.zip"
)
ARCHIVE="$DOWNLOAD_DIR/electricity_load_diagrams.zip"
ok=0
for url in "${URLS[@]}"; do
  if curl -fL --retry 3 --retry-delay 2 -o "$ARCHIVE" "$url"; then
    ok=1
    break
  fi
done
test "$ok" -eq 1
unzip -o "$ARCHIVE" -d "$EXTRACT_DIR" >/dev/null
for z in "$EXTRACT_DIR"/*.zip; do
  [ -e "$z" ] || continue
  unzip -o "$z" -d "$EXTRACT_DIR" >/dev/null
done
rm -rf "$EXTRACT_DIR/__MACOSX"
test -f "$EXTRACT_DIR/LD2011_2014.txt"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
