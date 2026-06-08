#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="cisa_kev_catalog"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
OUT="$DOWNLOAD_DIR/cisa_kev_catalog.json"
TMP="$OUT.tmp"
URL="https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$TMP"
  curl --globoff -fL --retry 3 --retry-delay 2 -A "openzl-public-datasets/1.0" -o "$TMP" "$URL"
  python3 - <<'PYV' "$TMP"
import json, sys
obj=json.load(open(sys.argv[1], encoding='utf-8'))
if not (isinstance(obj, dict) and isinstance(obj.get('vulnerabilities'), list)):
    raise SystemExit('bad cisa_kev_catalog payload')
PYV
  mv "$TMP" "$OUT"
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
