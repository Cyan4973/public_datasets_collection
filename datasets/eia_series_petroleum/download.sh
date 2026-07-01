#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eia_series_petroleum"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_FILE="$DOWNLOAD_DIR/download_failures.tsv"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"
COMBINED="$DOWNLOAD_DIR/eia_series_petroleum.json"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${EIA_PETROLEUM_URL:-https://api.eia.gov/v2/petroleum/pri/spt/data/}"
API_KEY="${EIA_API_KEY:-DEMO_KEY}"
PAGE_SIZE="${EIA_PETROLEUM_PAGE_SIZE:-5000}"
MIN_RECORDS="${EIA_PETROLEUM_MIN_RECORDS:-80000}"
MAX_RECORDS="${EIA_PETROLEUM_MAX_RECORDS:-120000}"
UA="${USER_AGENT:-openzl-public-datasets/1.0 (numeric dataset collection)}"

: > "$FAIL_FILE"

if [ -s "$INVENTORY" ] && [ -s "$COMBINED" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  python3 - <<'PY' "$INVENTORY" "$MIN_RECORDS"
import json
import sys

inventory = json.load(open(sys.argv[1], encoding="utf-8"))
records = int(inventory.get("record_count", 0))
if records < int(sys.argv[2]):
    raise SystemExit(1)
print(f"inventory cache_hit page_count={inventory.get('page_count')} record_count={records}")
PY
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

rm -rf "$PAGE_DIR.tmp"
mkdir -p "$PAGE_DIR.tmp"

export BASE_URL API_KEY PAGE_SIZE MIN_RECORDS MAX_RECORDS PAGE_DIR_TMP="$PAGE_DIR.tmp" UA DATASET_ID
python3 - <<'PY'
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlencode

base_url = os.environ["BASE_URL"]
api_key = os.environ["API_KEY"]
page_size = int(os.environ["PAGE_SIZE"])
min_records = int(os.environ["MIN_RECORDS"])
max_records = int(os.environ["MAX_RECORDS"])
page_dir = Path(os.environ["PAGE_DIR_TMP"])
ua = os.environ["UA"]
dataset_id = os.environ["DATASET_ID"]

if page_size < 1 or page_size > 5000:
    raise SystemExit("EIA_PETROLEUM_PAGE_SIZE must be between 1 and 5000")
if max_records < min_records:
    raise SystemExit("EIA_PETROLEUM_MAX_RECORDS must be >= EIA_PETROLEUM_MIN_RECORDS")

all_rows = []
pages = []
source_bytes = 0
api_total = None
offset = 0

while len(all_rows) < max_records:
    params = [
        ("api_key", api_key),
        ("frequency", "daily"),
        ("data[0]", "value"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
        ("offset", str(offset)),
        ("length", str(page_size)),
    ]
    sep = "&" if "?" in base_url else "?"
    url = base_url + sep + urlencode(params)
    page_number = len(pages) + 1
    out = page_dir / f"page_{page_number:05d}.json"
    print(f"fetch_page page={page_number} offset={offset} url={url}")
    try:
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
                "-o",
                str(out),
                url,
            ],
            check=True,
        )
    except subprocess.CalledProcessError:
        raise SystemExit(f"curl_failed page={page_number} offset={offset} url={url}")

    size = out.stat().st_size
    source_bytes += size
    obj = json.loads(out.read_text(encoding="utf-8"))
    response = obj.get("response") or {}
    data = response.get("data")
    if not isinstance(data, list):
        raise SystemExit(f"page {page_number}: missing response.data list")
    if api_total is None and response.get("total") is not None:
        api_total = int(response["total"])
    all_rows.extend(data)
    pages.append(
        {
            "page": page_number,
            "offset": offset,
            "length": page_size,
            "local_path": out.name,
            "record_count": len(data),
            "bytes": size,
            "url": url,
        }
    )
    print(f"page_ok page={page_number} records={len(data)} total_records={len(all_rows)} api_total={api_total}")
    if not data or len(data) < page_size:
        break
    offset += page_size
    if api_total is not None and offset >= api_total:
        break

record_count = min(len(all_rows), max_records)
all_rows = all_rows[:record_count]
if record_count < min_records:
    raise SystemExit(f"only {record_count} records < EIA_PETROLEUM_MIN_RECORDS={min_records}")

combined = {
    "response": {
        "total": api_total,
        "frequency": "daily",
        "data": all_rows,
    },
    "download": {
        "dataset_id": dataset_id,
        "base_url": base_url,
        "page_size": page_size,
        "page_count": len(pages),
        "record_count": record_count,
        "api_total": api_total,
    },
}
(page_dir / "eia_series_petroleum.json").write_text(
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
cp "$PAGE_DIR/eia_series_petroleum.json" "$COMBINED"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
