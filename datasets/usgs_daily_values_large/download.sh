#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_daily_values_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
URL='https://waterservices.usgs.gov/nwis/dv/?format=json&sites=01646500,02087500,07374000&startDT=2023-01-01&endDT=2024-12-31&parameterCd=00060,00065&siteStatus=all'
OUT="$DOWNLOAD_DIR/usgs_daily_values_large.json"
TMP="$OUT.tmp"
if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$TMP"
  curl --globoff -fL --retry 3 --retry-delay 2 -o "$TMP" "$URL"
  jq -e '.value.timeSeries != null' "$TMP" >/dev/null
  mv "$TMP" "$OUT"
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
