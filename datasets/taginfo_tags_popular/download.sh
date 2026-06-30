#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="taginfo_tags_popular"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_FILE="$DOWNLOAD_DIR/download_failures.tsv"
INVENTORY="$DOWNLOAD_DIR/download_inventory.json"
COMBINED="$DOWNLOAD_DIR/taginfo_tags_popular.json"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${TAGINFO_TAGS_POPULAR_URL:-https://taginfo.openstreetmap.org/api/4/tags/popular}"
PAGE_SIZE="${TAGINFO_TAGS_PAGE_SIZE:-500}"
MAX_PAGES="${TAGINFO_TAGS_MAX_PAGES:-80}"
MIN_RECORDS="${TAGINFO_TAGS_MIN_RECORDS:-14000}"
MAX_RECORDS="${TAGINFO_TAGS_MAX_RECORDS:-20000}"
REQUEST_DELAY="${TAGINFO_TAGS_REQUEST_DELAY_SECONDS:-0.2}"
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

if [ -d "$PAGE_DIR.tmp" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && compgen -G "$PAGE_DIR.tmp/page_*.json" >/dev/null; then
  echo "resume_existing_tmp_pages path=$PAGE_DIR.tmp"
  export PAGE_DIR_TMP="$PAGE_DIR.tmp" MIN_RECORDS MAX_RECORDS BASE_URL PAGE_SIZE DATASET_ID
  python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

page_dir = Path(os.environ["PAGE_DIR_TMP"])
min_records = int(os.environ["MIN_RECORDS"])
max_records = int(os.environ["MAX_RECORDS"])
base_url = os.environ["BASE_URL"]
page_size = int(os.environ["PAGE_SIZE"])
dataset_id = os.environ["DATASET_ID"]

combined_rows = []
pages = []
seen_pairs: set[tuple[str, str]] = set()
api_total = None
source_bytes = 0
for page_file in sorted(page_dir.glob("page_*.json")):
    obj = json.loads(page_file.read_text(encoding="utf-8"))
    data = obj.get("data")
    if not isinstance(data, list):
        raise SystemExit(f"{page_file}: missing data list")
    if api_total is None and obj.get("total") is not None:
        api_total = int(obj["total"])
    page_records = 0
    for row in data:
        pair = (str(row.get("key") or ""), str(row.get("value") or ""))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        combined_rows.append(row)
        page_records += 1
        if len(combined_rows) >= max_records:
            break
    source_bytes += page_file.stat().st_size
    pages.append(
        {
            "page": len(pages) + 1,
            "local_path": page_file.name,
            "record_count": page_records,
            "raw_record_count": len(data),
            "bytes": page_file.stat().st_size,
            "url": "",
        }
    )
record_count = len(combined_rows)
if record_count < min_records:
    raise SystemExit(f"only {record_count} records < TAGINFO_TAGS_MIN_RECORDS={min_records}")

(page_dir / "taginfo_tags_popular.json").write_text(
    json.dumps(
        {
            "data": combined_rows,
            "download": {
                "dataset_id": dataset_id,
                "base_url": base_url,
                "page_size": page_size,
                "page_count": len(pages),
                "record_count": record_count,
                "api_total": api_total,
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
(page_dir / "download_inventory.json").write_text(
    json.dumps(
        {
            "dataset_id": dataset_id,
            "base_url": base_url,
            "page_size": page_size,
            "page_count": len(pages),
            "record_count": record_count,
            "api_total": api_total,
            "source_bytes": source_bytes,
            "pages": pages,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
print(f"semantic_validation=ok existing_tmp_pages={len(pages)} records={record_count} source_bytes={source_bytes}")
PY
  rm -rf "$PAGE_DIR"
  mv "$PAGE_DIR.tmp" "$PAGE_DIR"
  cp "$PAGE_DIR/download_inventory.json" "$INVENTORY"
  cp "$PAGE_DIR/taginfo_tags_popular.json" "$COMBINED"
  echo "[$(date -Is)] download done dataset=$DATASET_ID"
  exit 0
fi

rm -rf "$PAGE_DIR.tmp"
mkdir -p "$PAGE_DIR.tmp"

export BASE_URL PAGE_SIZE MAX_PAGES MIN_RECORDS MAX_RECORDS REQUEST_DELAY PAGE_DIR_TMP="$PAGE_DIR.tmp" UA DATASET_ID
python3 - <<'PY'
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

base_url = os.environ["BASE_URL"]
page_size = int(os.environ["PAGE_SIZE"])
max_pages = int(os.environ["MAX_PAGES"])
min_records = int(os.environ["MIN_RECORDS"])
max_records = int(os.environ["MAX_RECORDS"])
request_delay = float(os.environ["REQUEST_DELAY"])
page_dir = Path(os.environ["PAGE_DIR_TMP"])
ua = os.environ["UA"]
dataset_id = os.environ["DATASET_ID"]

if page_size < 1 or page_size > 1000:
    raise SystemExit("TAGINFO_TAGS_PAGE_SIZE must be between 1 and 1000")
if max_records < min_records:
    raise SystemExit("TAGINFO_TAGS_MAX_RECORDS must be >= TAGINFO_TAGS_MIN_RECORDS")

record_count = 0
source_bytes = 0
api_total = None
pages = []
combined_rows = []
seen_pairs: set[tuple[str, str]] = set()

for page_number in range(1, max_pages + 1):
    params = urlencode({"page": page_number, "rp": page_size})
    sep = "&" if "?" in base_url else "?"
    url = f"{base_url}{sep}{params}"
    out = page_dir / f"page_{page_number:05d}.json"
    print(f"fetch_page page={page_number} url={url}")
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
        raise SystemExit(f"curl_failed page={page_number} url={url}")
    size = out.stat().st_size
    source_bytes += size
    obj = json.loads(out.read_text(encoding="utf-8"))
    data = obj.get("data")
    if not isinstance(data, list):
        raise SystemExit(f"page {page_number}: missing data list")
    if api_total is None and obj.get("total") is not None:
        api_total = int(obj["total"])

    page_records = 0
    for row in data:
        key = str(row.get("key") or "")
        value = str(row.get("value") or "")
        pair = (key, value)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        combined_rows.append(row)
        page_records += 1
        if len(combined_rows) >= max_records:
            break
    record_count = len(combined_rows)
    pages.append(
        {
            "page": page_number,
            "local_path": out.name,
            "record_count": page_records,
            "raw_record_count": len(data),
            "bytes": size,
            "url": url,
        }
    )
    print(f"page_ok page={page_number} records={page_records} total_records={record_count}")
    if len(data) == 0 or len(data) < page_size:
        break
    if api_total is not None and page_number * page_size >= api_total:
        break
    if record_count >= max_records:
        break
    time.sleep(request_delay)

if record_count < min_records:
    raise SystemExit(f"only {record_count} records < TAGINFO_TAGS_MIN_RECORDS={min_records}")

combined = {
    "data": combined_rows,
    "download": {
        "dataset_id": dataset_id,
        "base_url": base_url,
        "page_size": page_size,
        "page_count": len(pages),
        "record_count": record_count,
        "api_total": api_total,
    },
}
(page_dir / "taginfo_tags_popular.json").write_text(
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
cp "$PAGE_DIR/taginfo_tags_popular.json" "$COMBINED"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
