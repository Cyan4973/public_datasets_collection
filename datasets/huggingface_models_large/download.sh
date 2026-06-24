#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="huggingface_models_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# HuggingFace Hub models, sorted by downloads desc (so the fetched head is dense, non-zero),
# via cursor pagination (the API returns a Link: rel="next" header). The build extracts
# downloads + likes (u32) per model, partitioned by creation year.
START_URL="${HF_START_URL:-https://huggingface.co/api/models?limit=100&full=false&sort=downloads&direction=-1}"
MAX_PAGES="${HF_MAX_PAGES:-250}"
SLEEP="${HF_SLEEP:-0.4}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"

fetch_page() {  # url outfile hdrfile -> echoes "<items>"
  local url="$1" out="$2" hdr="$3"
  curl --globoff -fsSL --retry 6 --retry-delay 5 --retry-all-errors \
    --speed-limit 1 --speed-time 60 \
    -A "$UA" -H "Accept: application/json" -D "$hdr" -o "$out" "$url"
  python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(len(d) if isinstance(d,list) else 0)" "$out"
}

next_from_hdr() {  # hdrfile -> next url or empty
  grep -i '^link:' "$1" 2>/dev/null | sed -n 's/.*<\([^>]*\)>; *rel="next".*/\1/p' | head -1
}

# fail-fast page 1
FIRST="$PAGES_DIR/page_0001.json"
FIRST_HDR="$DOWNLOAD_DIR/.hdr_0001"
if [ ! -s "$FIRST" ]; then
  echo "probe page=1"
  n="$(fetch_page "$START_URL" "$FIRST" "$FIRST_HDR")" || { echo "FATAL: first HF request failed."; rm -f "$FIRST"; exit 1; }
  [ "${n:-0}" -le 0 ] && { echo "FATAL: page 1 returned 0 models."; rm -f "$FIRST"; exit 1; }
  echo "probe ok models=$n"
  sleep "$SLEEP"
fi

# resume: derive next url from the last contiguous page's saved header
url=""
hdr="$DOWNLOAD_DIR/.hdr_last"
# rebuild the cursor chain from page 1 forward using saved headers when present
page=1
while :; do
  out="$(printf '%s/page_%04d.json' "$PAGES_DIR" "$page")"
  h="$(printf '%s/.hdr_%04d' "$DOWNLOAD_DIR" "$page")"
  if [ ! -s "$out" ]; then break; fi
  url="$(next_from_hdr "$h")"
  page=$((page + 1))
done

pages_fetched=0
while [ -n "$url" ] && [ "$page" -le "$MAX_PAGES" ]; do
  out="$(printf '%s/page_%04d.json' "$PAGES_DIR" "$page")"
  h="$(printf '%s/.hdr_%04d' "$DOWNLOAD_DIR" "$page")"
  if ! n="$(fetch_page "$url" "$out" "$h")"; then
    echo "WARN: fetch failed page=$page (stopping)"; rm -f "$out"; break
  fi
  pages_fetched=$((pages_fetched + 1))
  [ "${n:-0}" -le 0 ] && { rm -f "$out"; break; }
  url="$(next_from_hdr "$h")"
  page=$((page + 1))
  sleep "$SLEEP"
done

have="$(find "$PAGES_DIR" -maxdepth 1 -type f -name 'page_*.json' | wc -l | tr -d ' ')"
echo "[$(date -Is)] download done dataset=$DATASET_ID pages_fetched=$pages_fetched pages_on_disk=$have"
test "$have" -ge 5
