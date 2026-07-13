#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="met_biocollection_objects"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_FILE="$DOWNLOAD_DIR/download_failures.tsv"
OUT="$DOWNLOAD_DIR/met_biocollection_objects.json"
TMP="$OUT.tmp"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
: > "$FAIL_FILE"
if [[ "${FORCE_DOWNLOAD:-0}" != "1" && -s "$OUT" ]]; then
  echo "cache_hit dataset=$DATASET_ID path=$OUT"
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi
rm -f "$TMP"
URL="https://collectionapi.metmuseum.org/public/collection/v1/search?hasImages=true&q=bird"
if ! curl --globoff -fL --retry 2 --retry-delay 2 -A "openzl-public-datasets/1.0" -o "$TMP" "$URL"; then
  echo -e "met_biocollection_objects\tcurl_failed\t$URL" >> "$FAIL_FILE"; rm -f "$TMP"; exit 1
fi
python3 - <<'PY' "$TMP"
import json, sys
obj=json.load(open(sys.argv[1], encoding='utf-8'))
assert isinstance(obj, dict) and 'objectIDs' in obj and len(obj['objectIDs']) > 0
PY
mv "$TMP" "$OUT"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
