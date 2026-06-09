#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="crossref_works_large_retry"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
OUT="$DOWNLOAD_DIR/crossref_works_large_retry.json"
URL="https://api.crossref.org/works?rows=500&filter=from-pub-date:2024-01-01,until-pub-date:2024-12-31"
if [[ -f "$OUT" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
  exit 0
fi
TMP="$OUT.tmp"
curl --globoff -L --fail --retry 2 --retry-delay 2 -A 'openzl-public-datasets/1.0' -o "$TMP" "$URL"
python3 - <<'PY' "$TMP"
import json, sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
assert isinstance(obj,dict) and isinstance(obj.get('message',{}).get('items'),list) and len(obj['message']['items'])>0
PY
mv "$TMP" "$OUT"
echo "[$(date -Is)] download done dataset=$DATASET_ID path=$OUT bytes=$(wc -c < "$OUT")"
