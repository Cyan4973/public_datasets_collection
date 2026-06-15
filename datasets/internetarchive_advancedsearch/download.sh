#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID='internetarchive_advancedsearch'
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
URL='https://archive.org/advancedsearch.php?q=mediatype:texts&fl[]=identifier&fl[]=downloads&fl[]=item_size&rows=10000&page=1&sort[]=identifierSorter+asc&output=json'
OUT="$DOWNLOAD_DIR/internetarchive_advancedsearch.json"
TMP="$OUT.tmp"
if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$TMP"
  curl --globoff -fL --retry 3 --retry-delay 2 -A "openzl-public-datasets/1.0" -o "$TMP" "$URL"
  python3 - <<'PY' "$TMP"
import json
import sys

path = sys.argv[1]
obj = json.load(open(path, encoding="utf-8"))
docs = obj.get("response", {}).get("docs")
if not isinstance(docs, list) or len(docs) < 10000:
    raise SystemExit(f"bad internetarchive_advancedsearch payload: docs={0 if docs is None else len(docs)}")
PY
  mv "$TMP" "$OUT"
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
