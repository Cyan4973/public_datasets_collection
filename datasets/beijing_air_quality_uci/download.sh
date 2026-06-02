#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="beijing_air_quality_uci"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"
ARCHIVE="$DOWNLOAD_DIR/beijing_multi_site_air_quality.zip"
curl -fL --retry 3 --retry-delay 2 -o "$ARCHIVE" https://archive.ics.uci.edu/static/public/501/beijing+multi+site+air+quality+data.zip
unzip -o "$ARCHIVE" -d "$EXTRACT_DIR" >/dev/null
INNER_ARCHIVE="$EXTRACT_DIR/PRSA2017_Data_20130301-20170228.zip"
test -f "$INNER_ARCHIVE"
unzip -o "$INNER_ARCHIVE" -d "$EXTRACT_DIR" >/dev/null
test -d "$EXTRACT_DIR/PRSA_Data_20130301-20170228"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
