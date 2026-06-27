#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gleif_lei_records"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${GLEIF_LEI_URL:-https://api.gleif.org/api/v1/lei-records}"
PAGE_SIZE="${GLEIF_PAGE_SIZE:-200}"
MAX_PAGES="${GLEIF_MAX_PAGES:-50}"
MAX_RECORDS="${GLEIF_MAX_RECORDS:-10000}"
MIN_RECORDS="${GLEIF_MIN_RECORDS:-5000}"
MAX_TOTAL_BYTES="${GLEIF_MAX_TOTAL_BYTES:-300000000}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"

if [ -s "$INVENTORY" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
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

export BASE_URL PAGE_SIZE MAX_PAGES MAX_RECORDS MIN_RECORDS MAX_TOTAL_BYTES PAGE_DIR_TMP="$PAGE_DIR.tmp" UA
python3 - <<'PY'
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlencode

base_url = os.environ["BASE_URL"]
page_size = int(os.environ["PAGE_SIZE"])
max_pages = int(os.environ["MAX_PAGES"])
max_records = int(os.environ["MAX_RECORDS"])
min_records = int(os.environ["MIN_RECORDS"])
max_total_bytes = int(os.environ["MAX_TOTAL_BYTES"])
page_dir = Path(os.environ["PAGE_DIR_TMP"])
ua = os.environ["UA"]

record_count = 0
total_bytes = 0
pages = []

for page_number in range(1, max_pages + 1):
    params = urlencode({"page[number]": page_number, "page[size]": page_size})
    sep = "&" if "?" in base_url else "?"
    url = f"{base_url}{sep}{params}"
    out = page_dir / f"page_{page_number:05d}.json"
    print(f"fetch_page page={page_number} url={url}")
    subprocess.run(
        [
            "curl",
            "--globoff",
            "-fL",
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "-A",
            ua,
            "-H",
            "Accept: application/vnd.api+json",
            "-o",
            str(out),
            url,
        ],
        check=True,
    )
    size = out.stat().st_size
    total_bytes += size
    if total_bytes > max_total_bytes:
        raise SystemExit(f"downloaded bytes exceed cap: {total_bytes} > {max_total_bytes}")
    obj = json.loads(out.read_text(encoding="utf-8"))
    data = obj.get("data")
    if not isinstance(data, list):
        raise SystemExit(f"page {page_number}: missing data list")
    page_records = len(data)
    record_count += page_records
    pages.append({"page": page_number, "local_path": out.name, "record_count": page_records, "bytes": size, "url": url})
    print(f"page_ok page={page_number} records={page_records} total_records={record_count}")
    if page_records == 0 or record_count >= max_records:
        break

if record_count < min_records:
    raise SystemExit(f"only {record_count} records < GLEIF_MIN_RECORDS={min_records}")

inventory = {
    "dataset_id": "gleif_lei_records",
    "base_url": base_url,
    "page_size": page_size,
    "page_count": len(pages),
    "record_count": record_count,
    "source_bytes": total_bytes,
    "pages": pages,
}
(page_dir / "download_inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"semantic_validation=ok pages={len(pages)} records={record_count} source_bytes={total_bytes}")
PY

rm -rf "$PAGE_DIR"
mv "$PAGE_DIR.tmp" "$PAGE_DIR"
cp "$PAGE_DIR/download_inventory.json" "$INVENTORY"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
