#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="rhea_reactions"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_FILE="$DOWNLOAD_DIR/download_failures.tsv"
OUT="$DOWNLOAD_DIR/rhea_reactions.json"
TMP="$OUT.tmp"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
: > "$FAIL_FILE"
if [[ "${FORCE_DOWNLOAD:-0}" != "1" && -s "$OUT" ]]; then
  echo "cache_hit dataset=$DATASET_ID path=$OUT"
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi
rm -f "$TMP"
URL="https://www.rhea-db.org/rhea?query=*&columns=rhea-id,equation,chebi-id&format=json&page=1&pageSize=20000"
if ! curl --globoff -fL --retry 2 --retry-delay 2 -A "openzl-public-datasets/1.0" -o "$TMP" "$URL"; then
  echo -e "rhea_reactions\tcurl_failed\t$URL" >> "$FAIL_FILE"; rm -f "$TMP"; exit 1
fi
python3 - <<'PY' "$TMP"
import json, sys
obj=json.load(open(sys.argv[1], encoding='utf-8'))
assert isinstance(obj, dict) and 'results' in obj and len(obj['results']) > 1000
PY
mv "$TMP" "$OUT"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
