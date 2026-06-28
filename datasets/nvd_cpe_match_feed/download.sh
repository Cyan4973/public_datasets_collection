#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nvd_cpe_match_feed"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${NVD_CPE_MATCH_URL:-https://services.nvd.nist.gov/rest/json/cpematch/2.0}"
PAGE_SIZE="${NVD_CPE_MATCH_PAGE_SIZE:-500}"
MAX_RECORDS="${NVD_CPE_MATCH_MAX_RECORDS:-10000}"
MIN_RECORDS="${NVD_CPE_MATCH_MIN_RECORDS:-5000}"
REQUEST_DELAY="${NVD_CPE_MATCH_REQUEST_DELAY_SECONDS:-6}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
OUT="$DOWNLOAD_DIR/nvd_cpe_match_feed.json"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"

if [ -s "$OUT" ] && [ -s "$INVENTORY" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  python3 - <<'PY' "$INVENTORY" "$MIN_RECORDS"
import json
import sys

obj = json.load(open(sys.argv[1], encoding="utf-8"))
records = int(obj.get("record_count", 0))
if records < int(sys.argv[2]):
    raise SystemExit(1)
print(f"inventory cache_hit record_count={records} pages={obj.get('page_count')}")
PY
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

case "$PAGE_SIZE" in
  ''|*[!0-9]*) echo "NVD_CPE_MATCH_PAGE_SIZE must be an integer" >&2; exit 1 ;;
esac
case "$MAX_RECORDS" in
  ''|*[!0-9]*) echo "NVD_CPE_MATCH_MAX_RECORDS must be an integer" >&2; exit 1 ;;
esac
case "$MIN_RECORDS" in
  ''|*[!0-9]*) echo "NVD_CPE_MATCH_MIN_RECORDS must be an integer" >&2; exit 1 ;;
esac
if [ "$PAGE_SIZE" -le 0 ] || [ "$MAX_RECORDS" -le 0 ] || [ "$MIN_RECORDS" -le 0 ]; then
  echo "NVD_CPE_MATCH_PAGE_SIZE, NVD_CPE_MATCH_MAX_RECORDS, and NVD_CPE_MATCH_MIN_RECORDS must be positive" >&2
  exit 1
fi
if [ "$PAGE_SIZE" -gt 500 ]; then
  echo "NVD_CPE_MATCH_PAGE_SIZE must be <= 500 for the NVD CPE Match Criteria API" >&2
  exit 1
fi
if [ "$MIN_RECORDS" -gt "$MAX_RECORDS" ]; then
  echo "NVD_CPE_MATCH_MIN_RECORDS cannot exceed NVD_CPE_MATCH_MAX_RECORDS" >&2
  exit 1
fi

TMP_PAGES="$DOWNLOAD_DIR/pages.tmp.$$"
TMP_OUT="$OUT.tmp"
TMP_INVENTORY="$INVENTORY.tmp"
rm -rf "$TMP_PAGES"
mkdir -p "$TMP_PAGES"
trap 'rm -rf "$TMP_PAGES" "$TMP_OUT" "$TMP_INVENTORY"' EXIT

start_index=0
page_index=0
record_count=0
total_results=-1

while [ "$record_count" -lt "$MAX_RECORDS" ]; do
  remaining=$((MAX_RECORDS - record_count))
  request_size="$PAGE_SIZE"
  if [ "$remaining" -lt "$request_size" ]; then
    request_size="$remaining"
  fi
  page_name=$(printf "page_%05d.json" "$page_index")
  page_path="$TMP_PAGES/$page_name"
  tmp_page="$page_path.tmp"
  curl_args=(
    --globoff
    --fail
    --location
    --get
    --retry 3
    --retry-delay 2
    --silent
    --show-error
    -A "$UA"
    -o "$tmp_page"
    --data-urlencode "startIndex=$start_index"
    --data-urlencode "resultsPerPage=$request_size"
  )
  if [ -n "${NVD_API_KEY:-}" ]; then
    curl_args+=(-H "apiKey: $NVD_API_KEY")
  fi

  echo "fetch_json page=$page_index startIndex=$start_index resultsPerPage=$request_size base_url=$BASE_URL"
  curl "${curl_args[@]}" "$BASE_URL"

  read -r page_records page_total < <(python3 - <<'PY' "$tmp_page"
import json
import sys

path = sys.argv[1]
obj = json.load(open(path, encoding="utf-8"))
rows = obj.get("matchStrings")
if not isinstance(rows, list):
    raise SystemExit("bad NVD CPE match payload: missing matchStrings list")
total = obj.get("totalResults", -1)
try:
    total = int(total)
except Exception:
    total = -1
print(len(rows), total)
PY
  )

  if [ "$page_records" -eq 0 ]; then
    rm -f "$tmp_page"
    echo "empty_page page=$page_index startIndex=$start_index"
    break
  fi

  mv "$tmp_page" "$page_path"
  record_count=$((record_count + page_records))
  total_results="$page_total"
  echo "fetch_json_ok page=$page_index records=$page_records cumulative_records=$record_count totalResults=$total_results"

  start_index=$((start_index + page_records))
  page_index=$((page_index + 1))

  if [ "$total_results" -ge 0 ] && [ "$start_index" -ge "$total_results" ]; then
    break
  fi
  if [ "$record_count" -ge "$MAX_RECORDS" ]; then
    break
  fi
  sleep "$REQUEST_DELAY"
done

python3 - <<'PY' "$TMP_PAGES" "$TMP_OUT" "$TMP_INVENTORY" "$BASE_URL" "$PAGE_SIZE" "$MAX_RECORDS" "$MIN_RECORDS" "$total_results"
from __future__ import annotations

import json
import sys
from pathlib import Path

pages_dir = Path(sys.argv[1])
out_path = Path(sys.argv[2])
inventory_path = Path(sys.argv[3])
base_url, page_size, max_records, min_records, total_results = sys.argv[4:]

combined = []
seen = set()
pages = sorted(pages_dir.glob("page_*.json"))
for page in pages:
    obj = json.loads(page.read_text(encoding="utf-8"))
    rows = obj.get("matchStrings")
    if not isinstance(rows, list):
        raise SystemExit(f"bad page payload: {page}")
    for wrapper in rows:
        if not isinstance(wrapper, dict):
            continue
        match = wrapper.get("matchString")
        if not isinstance(match, dict):
            continue
        key = match.get("matchCriteriaId") or json.dumps(match, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        combined.append(wrapper)

record_count = len(combined)
if record_count < int(min_records):
    raise SystemExit(f"only {record_count} unique match strings < NVD_CPE_MATCH_MIN_RECORDS={min_records}")

payload = {
    "format": "nvd_cpe_match_feed_combined_v1",
    "source": base_url,
    "page_count": len(pages),
    "record_count": record_count,
    "totalResults_reported": int(total_results),
    "matchStrings": combined,
}
out_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
inventory = {
    "dataset_id": "nvd_cpe_match_feed",
    "base_url": base_url,
    "page_size": int(page_size),
    "max_records": int(max_records),
    "min_records": int(min_records),
    "page_count": len(pages),
    "record_count": record_count,
    "totalResults_reported": int(total_results),
    "source_bytes": out_path.stat().st_size,
}
inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok unique_records={record_count} pages={len(pages)}")
PY

rm -rf "$PAGES_DIR"
mv "$TMP_PAGES" "$PAGES_DIR"
mv "$TMP_OUT" "$OUT"
mv "$TMP_INVENTORY" "$INVENTORY"
trap - EXIT
echo "[$(date -Is)] download done dataset=$DATASET_ID records=$record_count pages=$page_index"
