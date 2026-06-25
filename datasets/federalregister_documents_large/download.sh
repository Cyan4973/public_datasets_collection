#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="federalregister_documents_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

UA="${FEDREG_UA:-openzl-public-datasets/1.0}"
START_YEAR="${FEDREG_START_YEAR:-2010}"
END_YEAR="${FEDREG_END_YEAR:-2024}"
SLEEP="${FEDREG_SLEEP:-0.2}"
PER_PAGE=1000
MAX_PAGES_PER_MONTH=12   # months top out ~3.5k docs (4 pages); 12 is a safe ceiling
API="https://www.federalregister.gov/api/v1/documents.json"
FIELDS="fields%5B%5D=document_number&fields%5B%5D=page_length&fields%5B%5D=start_page"

# Each request is a tiny projected page; --max-time is fine for small per-page pulls.
get() { curl --globoff -fsS -A "$UA" --retry 5 --retry-delay 3 --max-time 90 "$@"; }

echo "[$(date -Is)] download start dataset=$DATASET_ID years=$START_YEAR..$END_YEAR"

fetched=0; skipped=0; months=0
for y in $(seq "$START_YEAR" "$END_YEAR"); do
  for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
    first="$y-$m-01"
    last="$(date -d "$first +1 month -1 day" +%Y-%m-%d)"
    cond="conditions%5Bpublication_date%5D%5Bgte%5D=$first&conditions%5Bpublication_date%5D%5Blte%5D=$last"
    months=$((months+1))
    page=1
    while [ "$page" -le "$MAX_PAGES_PER_MONTH" ]; do
      pp="$(printf '%02d' "$page")"
      out="$PAGES_DIR/${y}-${m}_p${pp}.json"
      if [ -s "$out" ]; then
        n="$(jq '.results | length' "$out" 2>/dev/null || echo 0)"
        skipped=$((skipped+1))
      else
        tmp="$out.tmp"; rm -f "$tmp"
        url="$API?per_page=$PER_PAGE&page=$page&$FIELDS&$cond"
        if get "$url" -o "$tmp" && jq -e '.results' "$tmp" >/dev/null 2>&1; then
          n="$(jq '.results | length' "$tmp")"
          mv "$tmp" "$out"; fetched=$((fetched+1))
        else
          rm -f "$tmp"; echo "[$(date -Is)] warn fetch_failed $y-$m page=$page"; break
        fi
        sleep "$SLEEP"
      fi
      [ "${n:-0}" -lt "$PER_PAGE" ] && break
      page=$((page+1))
    done
  done
done

echo "[$(date -Is)] download done dataset=$DATASET_ID months=$months fetched=$fetched skipped=$skipped pages=$(ls "$PAGES_DIR" | wc -l)"
