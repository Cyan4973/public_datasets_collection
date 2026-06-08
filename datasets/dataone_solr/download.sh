#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dataone_solr"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_FILE="$DOWNLOAD_DIR/download_failures.tsv"
OUT="$DOWNLOAD_DIR/dataone_solr.json"
TMP="$OUT.tmp"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
: > "$FAIL_FILE"
if [[ "${FORCE_DOWNLOAD:-0}" != "1" && -s "$OUT" ]]; then
  echo "cache_hit dataset=$DATASET_ID path=$OUT"
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi
rm -f "$TMP"
URL="https://cn.dataone.org/cn/v2/query/solr/?q=*:*&rows=1000&wt=json"
if ! curl --globoff -fL --retry 2 --retry-delay 2 -A "openzl-public-datasets/1.0" -o "$TMP" "$URL"; then
  echo -e "dataone_solr\tcurl_failed\t$URL" >> "$FAIL_FILE"; rm -f "$TMP"; exit 1
fi
python3 - <<'PY' "$TMP"
import json, sys
obj=json.load(open(sys.argv[1], encoding='utf-8'))
assert isinstance(obj, dict) and 'response' in obj and len(obj['response'].get('docs', [])) > 0
PY
mv "$TMP" "$OUT"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
