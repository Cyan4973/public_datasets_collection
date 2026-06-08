#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sec_submissions_recent"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
fetch_one() {
  local name="$1"; local url="$2"; local out="$DOWNLOAD_DIR/$name.json"; local tmp="$out.tmp"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "[$(date -Is)] cache_hit dataset=$DATASET_ID path=$out"
    return 0
  fi
  rm -f "$tmp"
  curl --globoff -fL --retry 3 --retry-delay 2 -A "openzl-public-datasets/1.0" -o "$tmp" "$url"
  python3 - <<'PYV' "$tmp"
import json, sys
obj=json.load(open(sys.argv[1], encoding='utf-8'))
if not (isinstance(obj, dict) and 'filings' in obj and 'recent' in obj['filings']):
    raise SystemExit('bad sec_submissions_recent payload')
PYV
  mv "$tmp" "$out"
}
fetch_one aapl https://data.sec.gov/submissions/CIK0000320193.json
fetch_one msft https://data.sec.gov/submissions/CIK0000789019.json
echo "[$(date -Is)] download done dataset=$DATASET_ID"
