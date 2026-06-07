#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usaspending_agencies"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
URL="https://api.usaspending.gov/api/v2/references/toptier_agencies/"
OUT="$DOWNLOAD_DIR/usaspending_agencies.json"
TMP="$OUT.tmp"
if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$TMP"
  curl --globoff -fL --retry 3 --retry-delay 2 -A "openzl-public-datasets/1.0" \
  -o "$TMP" "$URL"
  python3 - <<'PYV' "$TMP"
import json, sys
obj=json.load(open(sys.argv[1],encoding="utf-8"))
if "results" not in obj:
    raise SystemExit("bad usaspending payload")
PYV
  mv "$TMP" "$OUT"
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
