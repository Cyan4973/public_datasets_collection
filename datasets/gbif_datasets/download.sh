#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gbif_datasets"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${GBIF_DATASETS_URL:-https://api.gbif.org/v1/dataset/search}"
PAGE_SIZE="${GBIF_PAGE_SIZE:-1000}"
MAX_PAGES="${GBIF_MAX_PAGES:-100}"
MAX_RECORDS="${GBIF_MAX_RECORDS:-100000}"
MIN_RECORDS="${GBIF_MIN_RECORDS:-5000}"
REQUEST_DELAY="${GBIF_REQUEST_DELAY_SECONDS:-0.1}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"
COMBINED="$DOWNLOAD_DIR/datasets.json"

if [ -s "$INVENTORY" ] && [ -s "$COMBINED" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  python3 - <<'PY' "$INVENTORY" "$MIN_RECORDS"
import json
import sys

obj = json.load(open(sys.argv[1], encoding="utf-8"))
records = int(obj.get("record_count", 0))
if records < int(sys.argv[2]):
    raise SystemExit(1)
print(f"inventory cache_hit record_count={records} page_count={obj.get('page_count')}")
PY
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

rm -rf "$PAGE_DIR.tmp"
mkdir -p "$PAGE_DIR.tmp"

export BASE_URL PAGE_SIZE MAX_PAGES MAX_RECORDS MIN_RECORDS REQUEST_DELAY PAGE_DIR_TMP="$PAGE_DIR.tmp" UA DATASET_ID
python3 - <<'PY'
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

base_url = os.environ["BASE_URL"]
page_size = int(os.environ["PAGE_SIZE"])
max_pages = int(os.environ["MAX_PAGES"])
max_records = int(os.environ["MAX_RECORDS"])
min_records = int(os.environ["MIN_RECORDS"])
request_delay = float(os.environ["REQUEST_DELAY"])
page_dir = Path(os.environ["PAGE_DIR_TMP"])
ua = os.environ["UA"]
dataset_id = os.environ["DATASET_ID"]

if page_size < 1 or page_size > 1000:
    raise SystemExit("GBIF_PAGE_SIZE must be between 1 and 1000")

record_count = 0
source_bytes = 0
api_total = None
pages = []
combined_rows = []

for page_number in range(max_pages):
    offset = page_number * page_size
    if offset >= max_records:
        break
    limit = min(page_size, max_records - offset)
    out = page_dir / f"page_{page_number:05d}.json"
    print(f"fetch_page page={page_number} offset={offset} limit={limit}")
    subprocess.run(
        [
            "curl",
            "--globoff",
            "-fL",
            "--get",
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "-A",
            ua,
            "-o",
            str(out),
            "--data-urlencode",
            f"limit={limit}",
            "--data-urlencode",
            f"offset={offset}",
            base_url,
        ],
        check=True,
    )
    size = out.stat().st_size
    source_bytes += size
    obj = json.loads(out.read_text(encoding="utf-8"))
    rows = obj.get("results")
    if not isinstance(rows, list):
        raise SystemExit(f"page {page_number}: missing results list")
    if api_total is None and obj.get("count") is not None:
        api_total = int(obj["count"])
    page_records = len(rows)
    record_count += page_records
    combined_rows.extend(rows)
    pages.append(
        {
            "page": page_number,
            "offset": offset,
            "limit": limit,
            "local_path": out.name,
            "record_count": page_records,
            "bytes": size,
        }
    )
    print(f"page_ok page={page_number} records={page_records} total_records={record_count}")
    if page_records == 0:
        break
    if page_records < limit:
        break
    if obj.get("endOfRecords") is True:
        break
    if api_total is not None and record_count >= api_total:
        break
    if record_count >= max_records:
        break
    time.sleep(request_delay)

if record_count < min_records:
    raise SystemExit(f"only {record_count} records < GBIF_MIN_RECORDS={min_records}")

combined = {
    "results": combined_rows,
    "count": api_total,
    "offset": 0,
    "limit": record_count,
    "download": {
        "dataset_id": dataset_id,
        "base_url": base_url,
        "page_size": page_size,
        "page_count": len(pages),
        "record_count": record_count,
        "api_total": api_total,
    },
}
(page_dir / "datasets.json").write_text(
    json.dumps(combined, separators=(",", ":"), sort_keys=True) + "\n",
    encoding="utf-8",
)
inventory = {
    "dataset_id": dataset_id,
    "base_url": base_url,
    "page_size": page_size,
    "page_count": len(pages),
    "record_count": record_count,
    "api_total": api_total,
    "source_bytes": source_bytes,
    "pages": pages,
}
(page_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"semantic_validation=ok pages={len(pages)} records={record_count} source_bytes={source_bytes}")
PY

rm -rf "$PAGE_DIR"
mv "$PAGE_DIR.tmp" "$PAGE_DIR"
cp "$PAGE_DIR/download_inventory.json" "$INVENTORY"
cp "$PAGE_DIR/datasets.json" "$COMBINED"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
