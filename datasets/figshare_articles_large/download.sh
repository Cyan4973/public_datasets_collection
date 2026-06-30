#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="figshare_articles_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${FIGSHARE_ARTICLES_LARGE_BASE_URL:-https://api.figshare.com/v2/articles}"
PAGE_SIZE="${FIGSHARE_ARTICLES_LARGE_PAGE_SIZE:-1000}"
TARGET_RECORDS="${FIGSHARE_ARTICLES_LARGE_TARGET_RECORDS:-20000}"
MIN_RECORDS="${FIGSHARE_ARTICLES_LARGE_MIN_RECORDS:-17000}"
REQUEST_DELAY="${FIGSHARE_ARTICLES_LARGE_REQUEST_DELAY_SECONDS:-1}"
ORDER_FIELD="${FIGSHARE_ARTICLES_LARGE_ORDER_FIELD:-published_date}"
ORDER_DIRECTIONS="${FIGSHARE_ARTICLES_LARGE_ORDER_DIRECTIONS:-desc asc}"
MAX_PAGES_PER_SLICE="${FIGSHARE_ARTICLES_LARGE_MAX_PAGES_PER_SLICE:-10}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
OUT="$DOWNLOAD_DIR/articles.json"
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

case "$PAGE_SIZE" in ''|*[!0-9]*) echo "FIGSHARE_ARTICLES_LARGE_PAGE_SIZE must be an integer" >&2; exit 1 ;; esac
case "$TARGET_RECORDS" in ''|*[!0-9]*) echo "FIGSHARE_ARTICLES_LARGE_TARGET_RECORDS must be an integer" >&2; exit 1 ;; esac
case "$MIN_RECORDS" in ''|*[!0-9]*) echo "FIGSHARE_ARTICLES_LARGE_MIN_RECORDS must be an integer" >&2; exit 1 ;; esac
case "$MAX_PAGES_PER_SLICE" in ''|*[!0-9]*) echo "FIGSHARE_ARTICLES_LARGE_MAX_PAGES_PER_SLICE must be an integer" >&2; exit 1 ;; esac
if [ "$PAGE_SIZE" -le 0 ] || [ "$TARGET_RECORDS" -le 0 ] || [ "$MIN_RECORDS" -le 0 ] || [ "$MAX_PAGES_PER_SLICE" -le 0 ]; then
  echo "FIGSHARE_ARTICLES_LARGE_PAGE_SIZE, FIGSHARE_ARTICLES_LARGE_TARGET_RECORDS, FIGSHARE_ARTICLES_LARGE_MIN_RECORDS, and FIGSHARE_ARTICLES_LARGE_MAX_PAGES_PER_SLICE must be positive" >&2
  exit 1
fi
if [ "$MIN_RECORDS" -gt "$TARGET_RECORDS" ]; then
  echo "FIGSHARE_ARTICLES_LARGE_MIN_RECORDS cannot exceed FIGSHARE_ARTICLES_LARGE_TARGET_RECORDS" >&2
  exit 1
fi

TMP_ROOT="$DOWNLOAD_DIR/tmp.$$"
TMP_PAGES="$TMP_ROOT/pages"
TMP_OUT="$TMP_ROOT/articles.json"
TMP_INVENTORY="$TMP_ROOT/download_inventory.json"
mkdir -p "$TMP_PAGES"
trap 'rm -rf "$TMP_ROOT"' EXIT

page_index=0
record_count=0
read -r -a order_directions <<< "$ORDER_DIRECTIONS"
for order_direction in "${order_directions[@]}"; do
  case "$order_direction" in
    asc|desc) ;;
    *) echo "unsupported FIGSHARE_ARTICLES_LARGE_ORDER_DIRECTIONS value: $order_direction" >&2; exit 1 ;;
  esac
  page=1
  pages_in_slice=0
  while [ "$record_count" -lt "$TARGET_RECORDS" ] && [ "$pages_in_slice" -lt "$MAX_PAGES_PER_SLICE" ]; do
    remaining=$((TARGET_RECORDS - record_count))
    request_size="$PAGE_SIZE"
    if [ "$remaining" -lt "$request_size" ]; then
      request_size="$remaining"
    fi
    page_path="$TMP_PAGES/$(printf '%05d' "$page_index")_${order_direction}_page_$(printf '%05d' "$page").json"
    echo "fetch_json slice=$order_direction order=$ORDER_FIELD page=$page page_index=$page_index page_size=$request_size"
    curl --globoff --fail --location --get --retry 3 --retry-delay 2 --retry-all-errors --silent --show-error \
      -A "$UA" -o "$page_path.tmp" \
      --data-urlencode "page=$page" \
      --data-urlencode "page_size=$request_size" \
      --data-urlencode "order=$ORDER_FIELD" \
      --data-urlencode "order_direction=$order_direction" \
      "$BASE_URL"
    page_records="$(python3 - <<'PY' "$page_path.tmp"
import json
import sys

obj = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(obj, list):
    raise SystemExit("bad Figshare article page: expected list")
print(len(obj))
PY
)"
    if [ "$page_records" -eq 0 ]; then
      rm -f "$page_path.tmp"
      echo "empty_page slice=$order_direction page=$page"
      break
    fi
    mv "$page_path.tmp" "$page_path"
    record_count=$((record_count + page_records))
    echo "fetch_json_ok slice=$order_direction page=$page records=$page_records cumulative_fetched_records=$record_count"
    page=$((page + 1))
    page_index=$((page_index + 1))
    pages_in_slice=$((pages_in_slice + 1))
    if [ "$page_records" -lt "$request_size" ]; then
      break
    fi
    if [ "$record_count" -lt "$TARGET_RECORDS" ]; then
      sleep "$REQUEST_DELAY"
    fi
  done
  if [ "$record_count" -ge "$TARGET_RECORDS" ]; then
    break
  fi
done

python3 - <<'PY' "$TMP_PAGES" "$TMP_OUT" "$TMP_INVENTORY" "$BASE_URL" "$TARGET_RECORDS" "$MIN_RECORDS" "$ORDER_FIELD" "$ORDER_DIRECTIONS" "$MAX_PAGES_PER_SLICE"
from __future__ import annotations

import json
import sys
from pathlib import Path

pages_dir = Path(sys.argv[1])
out_path = Path(sys.argv[2])
inventory_path = Path(sys.argv[3])
base_url = sys.argv[4]
target_records = int(sys.argv[5])
min_records = int(sys.argv[6])
order_field = sys.argv[7]
order_directions = sys.argv[8].split()
max_pages_per_slice = int(sys.argv[9])

rows = []
seen = set()
for page in sorted(pages_dir.glob("*.json")):
    page_rows = json.loads(page.read_text(encoding="utf-8"))
    if not isinstance(page_rows, list):
        raise SystemExit(f"bad page payload: {page}")
    for row in page_rows:
        if not isinstance(row, dict):
            continue
        key = row.get("id")
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
        if len(rows) >= target_records:
            break
    if len(rows) >= target_records:
        break
if len(rows) < min_records:
    raise SystemExit(f"only {len(rows)} unique articles < FIGSHARE_ARTICLES_LARGE_MIN_RECORDS={min_records}")

out_path.write_text(json.dumps(rows, separators=(",", ":")) + "\n", encoding="utf-8")
inventory = {
    "dataset_id": "figshare_articles_large",
    "base_url": base_url,
    "target_records": target_records,
    "min_records": min_records,
    "order_field": order_field,
    "order_directions": order_directions,
    "max_pages_per_slice": max_pages_per_slice,
    "page_count": len(list(pages_dir.glob("*.json"))),
    "record_count": len(rows),
    "source_bytes": out_path.stat().st_size,
}
inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok unique_records={len(rows)} pages={inventory['page_count']}")
PY

rm -rf "$PAGES_DIR"
mv "$TMP_PAGES" "$PAGES_DIR"
mv "$TMP_OUT" "$OUT"
mv "$TMP_INVENTORY" "$INVENTORY"
trap - EXIT
rm -rf "$TMP_ROOT"
echo "[$(date -Is)] download done dataset=$DATASET_ID records=$record_count pages=$page_index"
