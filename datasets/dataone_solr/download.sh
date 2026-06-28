#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dataone_solr"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${DATAONE_SOLR_URL:-https://cn.dataone.org/cn/v2/query/solr/}"
PAGE_SIZE="${DATAONE_SOLR_PAGE_SIZE:-1000}"
MAX_PAGES="${DATAONE_SOLR_MAX_PAGES:-100}"
MAX_RECORDS="${DATAONE_SOLR_MAX_RECORDS:-100000}"
MIN_RECORDS="${DATAONE_SOLR_MIN_RECORDS:-5000}"
REQUEST_DELAY="${DATAONE_SOLR_REQUEST_DELAY_SECONDS:-0.1}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"
COMBINED="$DOWNLOAD_DIR/dataone_solr.json"
FIELDS="id,size,numberReplicas,dateUploaded,updateDate,dateModified"

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

export BASE_URL PAGE_SIZE MAX_PAGES MAX_RECORDS MIN_RECORDS REQUEST_DELAY PAGE_DIR_TMP="$PAGE_DIR.tmp" UA DATASET_ID FIELDS
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
fields = os.environ["FIELDS"]

if page_size < 1 or page_size > 1000:
    raise SystemExit("DATAONE_SOLR_PAGE_SIZE must be between 1 and 1000")

record_count = 0
source_bytes = 0
num_found = None
pages = []
combined_docs = []

for page_number in range(max_pages):
    start = page_number * page_size
    if start >= max_records:
        break
    rows = min(page_size, max_records - start)
    out = page_dir / f"page_{page_number:05d}.json"
    print(f"fetch_page page={page_number} start={start} rows={rows}")
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
            "q=*:*",
            "--data-urlencode",
            f"rows={rows}",
            "--data-urlencode",
            f"start={start}",
            "--data-urlencode",
            "wt=json",
            "--data-urlencode",
            f"fl={fields}",
            "--data-urlencode",
            "sort=id asc",
            base_url,
        ],
        check=True,
    )
    size = out.stat().st_size
    source_bytes += size
    obj = json.loads(out.read_text(encoding="utf-8"))
    response = obj.get("response")
    if not isinstance(response, dict) or not isinstance(response.get("docs"), list):
        raise SystemExit(f"page {page_number}: missing response.docs list")
    docs = response["docs"]
    if num_found is None and response.get("numFound") is not None:
        num_found = int(response["numFound"])
    page_records = len(docs)
    record_count += page_records
    combined_docs.extend(docs)
    pages.append(
        {
            "page": page_number,
            "start": start,
            "rows": rows,
            "local_path": out.name,
            "record_count": page_records,
            "bytes": size,
        }
    )
    print(f"page_ok page={page_number} records={page_records} total_records={record_count}")
    if page_records == 0:
        break
    if page_records < rows:
        break
    if num_found is not None and record_count >= num_found:
        break
    if record_count >= max_records:
        break
    time.sleep(request_delay)

if record_count < min_records:
    raise SystemExit(f"only {record_count} records < DATAONE_SOLR_MIN_RECORDS={min_records}")

combined = {
    "response": {
        "docs": combined_docs,
        "numFound": num_found,
        "start": 0,
    },
    "download": {
        "dataset_id": dataset_id,
        "base_url": base_url,
        "page_size": page_size,
        "page_count": len(pages),
        "record_count": record_count,
        "num_found": num_found,
        "fields": fields,
    },
}
(page_dir / "dataone_solr.json").write_text(
    json.dumps(combined, separators=(",", ":"), sort_keys=True) + "\n",
    encoding="utf-8",
)
inventory = {
    "dataset_id": dataset_id,
    "base_url": base_url,
    "fields": fields,
    "page_size": page_size,
    "page_count": len(pages),
    "record_count": record_count,
    "num_found": num_found,
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
cp "$PAGE_DIR/dataone_solr.json" "$COMBINED"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
