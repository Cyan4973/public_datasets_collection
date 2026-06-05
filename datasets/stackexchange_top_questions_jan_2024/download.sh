#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="stackexchange_top_questions_jan_2024"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
URL="https://api.stackexchange.com/2.3/questions?fromdate=1704067200&todate=1706745599&order=desc&sort=votes&site=stackoverflow&pagesize=100"
OUT="$DOWNLOAD_DIR/stackexchange_top_questions_jan_2024.json"
TMP="$OUT.tmp"
if [ -s "$OUT" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$OUT"
else
  rm -f "$TMP"
  curl -fL --retry 3 --retry-delay 2 -o "$TMP" "$URL"
  python3 - <<'PY' "$TMP"
import json, sys
obj=json.load(open(sys.argv[1]))
if "items" not in obj:
    raise SystemExit("missing items")
PY
  mv "$TMP" "$OUT"
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID"
