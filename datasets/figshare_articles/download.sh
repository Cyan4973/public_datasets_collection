#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="figshare_articles"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
OUT="$DOWNLOAD_DIR/figshare_articles.json"
TMP="$OUT.tmp"
if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$TMP"
  curl --globoff -fL --retry 3 --retry-delay 2 -A "openzl-public-datasets/1.0"     -o "$TMP" "https://api.figshare.com/v2/articles?page_size=100"
  python3 - <<'PYV' "$TMP"
import json, sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
if not (isinstance(obj, list)):
    raise SystemExit('bad figshare_articles payload')
PYV
  mv "$TMP" "$OUT"
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
