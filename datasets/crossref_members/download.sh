#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="crossref_members"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# All Crossref members via deep cursor pagination (rows=1000 -> ~33 pages). Full member
# objects (the nested `counts` is not select-able); the build extracts DOI counts per member.
API="https://api.crossref.org/members"
ROWS="${CROSSREF_ROWS:-1000}"
MAX_PAGES="${CROSSREF_MAX_PAGES:-200}"
UA="openzl-public-datasets/1.0 (mailto:research@example.org)"

read_meta() {  # file -> "<items>\t<next_cursor>"
  python3 -c "import json,sys;m=json.load(open(sys.argv[1]))['message'];print(f\"{len(m['items'])}\t{m.get('next-cursor','')}\")" "$1"
}

fetch_page() {  # cursor outfile -> "<items>\t<next_cursor>"
  local cursor="$1" out="$2"
  curl --globoff -fsSL --retry 6 --retry-delay 5 --retry-all-errors \
    --speed-limit 1 --speed-time 120 \
    -A "$UA" -G \
    --data-urlencode "rows=$ROWS" \
    --data-urlencode "cursor=$cursor" \
    -o "$out" "$API"
  read_meta "$out"
}

# fail-fast page 1
FIRST="$PAGES_DIR/page_0001.json"
if [ ! -s "$FIRST" ]; then
  echo "probe page=1"
  if ! IFS=$'\t' read -r n cursor < <(fetch_page "*" "$FIRST"); then
    echo "FATAL: first Crossref request failed."; rm -f "$FIRST"; exit 1
  fi
  [ "${n:-0}" -le 0 ] && { echo "FATAL: page 1 returned 0 items."; rm -f "$FIRST"; exit 1; }
  echo "probe ok items=$n"
  sleep 1
fi

IFS=$'\t' read -r n cursor < <(read_meta "$FIRST")

pages_fetched=0
page=2
while [ -n "$cursor" ] && [ "$page" -le "$MAX_PAGES" ]; do
  [ "$n" -lt "$ROWS" ] && break   # previous page was the last
  out="$(printf '%s/page_%04d.json' "$PAGES_DIR" "$page")"
  if [ -s "$out" ]; then
    IFS=$'\t' read -r n cursor < <(read_meta "$out")
  else
    if ! IFS=$'\t' read -r n cursor < <(fetch_page "$cursor" "$out"); then
      echo "WARN: fetch failed page=$page (stopping)"; rm -f "$out"; break
    fi
    pages_fetched=$((pages_fetched + 1))
    sleep 1
  fi
  page=$((page + 1))
done

have="$(find "$PAGES_DIR" -maxdepth 1 -type f -name 'page_*.json' | wc -l | tr -d ' ')"
echo "[$(date -Is)] download done dataset=$DATASET_ID pages_fetched=$pages_fetched pages_on_disk=$have"
test "$have" -ge 5
