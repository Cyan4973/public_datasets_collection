#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openml_runs_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGES_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${OPENML_RUNS_LARGE_BASE_URL:-https://www.openml.org/api/v1/json/run/list}"
PAGE_SIZE="${OPENML_RUNS_LARGE_PAGE_SIZE:-1000}"
TARGET_RECORDS="${OPENML_RUNS_LARGE_TARGET_RECORDS:-20000}"
MIN_RECORDS="${OPENML_RUNS_LARGE_MIN_RECORDS:-10000}"
REQUEST_DELAY="${OPENML_RUNS_LARGE_REQUEST_DELAY_SECONDS:-1}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
OUT="$DOWNLOAD_DIR/runs.json"
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

case "$PAGE_SIZE" in ''|*[!0-9]*) echo "OPENML_RUNS_LARGE_PAGE_SIZE must be an integer" >&2; exit 1 ;; esac
case "$TARGET_RECORDS" in ''|*[!0-9]*) echo "OPENML_RUNS_LARGE_TARGET_RECORDS must be an integer" >&2; exit 1 ;; esac
case "$MIN_RECORDS" in ''|*[!0-9]*) echo "OPENML_RUNS_LARGE_MIN_RECORDS must be an integer" >&2; exit 1 ;; esac
if [ "$PAGE_SIZE" -le 0 ] || [ "$TARGET_RECORDS" -le 0 ] || [ "$MIN_RECORDS" -le 0 ]; then
  echo "OPENML_RUNS_LARGE_PAGE_SIZE, OPENML_RUNS_LARGE_TARGET_RECORDS, and OPENML_RUNS_LARGE_MIN_RECORDS must be positive" >&2
  exit 1
fi
if [ "$MIN_RECORDS" -gt "$TARGET_RECORDS" ]; then
  echo "OPENML_RUNS_LARGE_MIN_RECORDS cannot exceed OPENML_RUNS_LARGE_TARGET_RECORDS" >&2
  exit 1
fi

TMP_ROOT="$DOWNLOAD_DIR/tmp.$$"
TMP_PAGES="$TMP_ROOT/pages"
TMP_OUT="$TMP_ROOT/runs.json"
TMP_INVENTORY="$TMP_ROOT/download_inventory.json"
mkdir -p "$TMP_PAGES"
trap 'rm -rf "$TMP_ROOT"' EXIT

offset=0
page_index=0
record_count=0
while [ "$record_count" -lt "$TARGET_RECORDS" ]; do
  remaining=$((TARGET_RECORDS - record_count))
  request_size="$PAGE_SIZE"
  if [ "$remaining" -lt "$request_size" ]; then
    request_size="$remaining"
  fi
  page_path="$TMP_PAGES/page_$(printf '%05d' "$page_index").json"
  url="$BASE_URL/limit/$request_size/offset/$offset"
  echo "fetch_json page=$page_index offset=$offset limit=$request_size"
  curl --globoff --fail --location --retry 3 --retry-delay 2 --retry-all-errors --silent --show-error \
    -A "$UA" -o "$page_path.tmp" "$url"
  page_records="$(python3 - <<'PY' "$page_path.tmp"
import json
import sys

obj = json.load(open(sys.argv[1], encoding="utf-8"))
rows = (obj.get("runs") or {}).get("run")
if not isinstance(rows, list):
    raise SystemExit("bad OpenML run page: missing runs.run list")
print(len(rows))
PY
)"
  if [ "$page_records" -eq 0 ]; then
    rm -f "$page_path.tmp"
    echo "empty_page page=$page_index offset=$offset"
    break
  fi
  mv "$page_path.tmp" "$page_path"
  record_count=$((record_count + page_records))
  echo "fetch_json_ok page=$page_index records=$page_records cumulative_records=$record_count"
  page_index=$((page_index + 1))
  offset=$((offset + page_records))
  if [ "$page_records" -lt "$request_size" ]; then
    break
  fi
  if [ "$record_count" -lt "$TARGET_RECORDS" ]; then
    sleep "$REQUEST_DELAY"
  fi
done

python3 - <<'PY' "$TMP_PAGES" "$TMP_OUT" "$TMP_INVENTORY" "$BASE_URL" "$TARGET_RECORDS" "$MIN_RECORDS"
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

rows = []
seen = set()
for page in sorted(pages_dir.glob("page_*.json")):
    obj = json.loads(page.read_text(encoding="utf-8"))
    page_rows = (obj.get("runs") or {}).get("run")
    if not isinstance(page_rows, list):
        raise SystemExit(f"bad page payload: {page}")
    for row in page_rows:
        if not isinstance(row, dict):
            continue
        key = row.get("run_id")
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
        if len(rows) >= target_records:
            break
    if len(rows) >= target_records:
        break
if len(rows) < min_records:
    raise SystemExit(f"only {len(rows)} unique runs < OPENML_RUNS_LARGE_MIN_RECORDS={min_records}")

payload = {
    "format": "openml_runs_large_combined_v1",
    "source": base_url,
    "record_count": len(rows),
    "runs": {"run": rows},
}
out_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
inventory = {
    "dataset_id": "openml_runs_large",
    "base_url": base_url,
    "target_records": target_records,
    "min_records": min_records,
    "page_count": len(list(pages_dir.glob("page_*.json"))),
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
