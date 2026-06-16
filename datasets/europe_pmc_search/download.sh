#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="europe_pmc_search"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

START_DATE="${EUROPE_PMC_START_DATE:-2024-01-01}"
END_DATE="${EUROPE_PMC_END_DATE:-2024-01-31}"
PAGE_SIZE="${EUROPE_PMC_PAGE_SIZE:-1000}"
REQUEST_DELAY="${EUROPE_PMC_REQUEST_DELAY:-0.25}"
MIN_RECORDS="${MIN_RECORDS:-10000}"
MAX_SOURCE_BYTES="${MAX_SOURCE_BYTES:-300000000}"
QUERY="FIRST_PDATE:[$START_DATE TO $END_DATE]"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
INVENTORY_TSV="$DOWNLOAD_DIR/download_inventory.tsv"
INVENTORY_JSON="$DOWNLOAD_DIR/download_inventory.json"

printf "local_name\turl\tcursor\n" > "$PLAN"
printf "local_name\tcursor\thit_count\tresult_count\tnext_cursor\tsource_bytes\n" > "$INVENTORY_TSV"

make_url() {
  local cursor="$1"
  python3 - "$QUERY" "$cursor" "$PAGE_SIZE" <<'PY'
from __future__ import annotations

import sys
import urllib.parse

query, cursor, page_size = sys.argv[1:4]
params = {
    "query": query,
    "cursorMark": cursor,
    "resultType": "lite",
    "pageSize": page_size,
    "format": "json",
}
print("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params))
PY
}

validate_page() {
  local path="$1"
  python3 - "$path" <<'PY'
from __future__ import annotations

import json
import sys

path = sys.argv[1]
obj = json.load(open(path, encoding="utf-8"))
if "hitCount" not in obj or "resultList" not in obj:
    raise SystemExit(f"bad Europe PMC payload: {path}")
results = obj.get("resultList", {}).get("result", [])
if not isinstance(results, list):
    raise SystemExit(f"bad Europe PMC result list: {path}")
hit_count = int(obj.get("hitCount", 0))
next_cursor = str(obj.get("nextCursorMark", ""))
print(f"{hit_count}\t{len(results)}\t{next_cursor}")
PY
}

cursor="*"
page_index=0
records_seen=0
hit_count=-1
downloaded_total=0
new_fetches=0
while (( hit_count < 0 || records_seen < hit_count )); do
  local_name="europe_pmc_$(printf '%04d' "$page_index").json"
  url="$(make_url "$cursor")"
  target="$DOWNLOAD_DIR/$local_name"
  printf "%s\t%s\t%s\n" "$local_name" "$url" "$cursor" >> "$PLAN"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit page=$page_index cursor=$cursor path=$target"
  else
    tmp="$target.tmp"
    rm -f "$tmp"
    echo "fetch page=$page_index cursor=$cursor"
    curl --globoff -fL --retry 3 --retry-delay 5 -A "openzl-public-datasets/1.0" -o "$tmp" "$url"
    mv "$tmp" "$target"
    new_fetches=$((new_fetches + 1))
    if [[ "$REQUEST_DELAY" != "0" ]]; then
      sleep "$REQUEST_DELAY"
    fi
  fi
  page_info="$(validate_page "$target")"
  IFS=$'\t' read -r hit_count result_count next_cursor <<< "$page_info"
  size="$(wc -c < "$target")"
  downloaded_total=$((downloaded_total + size))
  if (( downloaded_total > MAX_SOURCE_BYTES )); then
    echo "downloaded source bytes exceed cap: $downloaded_total > $MAX_SOURCE_BYTES" >&2
    exit 1
  fi
  printf "%s\t%s\t%s\t%s\t%s\t%s\n" "$local_name" "$cursor" "$hit_count" "$result_count" "$next_cursor" "$size" >> "$INVENTORY_TSV"
  records_seen=$((records_seen + result_count))
  if (( result_count == 0 )); then
    break
  fi
  if [[ -z "$next_cursor" || "$next_cursor" == "$cursor" ]]; then
    break
  fi
  cursor="$next_cursor"
  page_index=$((page_index + 1))
done

export DOWNLOAD_DIR INVENTORY_TSV INVENTORY_JSON MIN_RECORDS MAX_SOURCE_BYTES START_DATE END_DATE QUERY
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
inventory_tsv = Path(os.environ["INVENTORY_TSV"])
inventory_json = Path(os.environ["INVENTORY_JSON"])
min_records = int(os.environ["MIN_RECORDS"])
max_source_bytes = int(os.environ["MAX_SOURCE_BYTES"])

records = []
seen_keys: set[tuple[str, str]] = set()
duplicate_keys: set[tuple[str, str]] = set()
source_bytes = 0
raw_records = 0
with inventory_tsv.open(encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh, delimiter="\t"):
        path = download_dir / row["local_name"]
        obj = json.load(open(path, encoding="utf-8"))
        keys = []
        for item in obj.get("resultList", {}).get("result", []):
            source = str(item.get("source", "")).strip()
            item_id = str(item.get("id", "")).strip()
            if not source or not item_id:
                continue
            key = (source, item_id)
            if key in seen_keys:
                duplicate_keys.add(key)
            seen_keys.add(key)
            keys.append(key)
        raw_records += len(keys)
        size = int(row["source_bytes"])
        source_bytes += size
        records.append({**row, "source_bytes": size, "record_count": len(keys)})

if len(seen_keys) < min_records:
    raise SystemExit(f"Europe PMC download below repair floor: records={len(seen_keys)} < {min_records}")
if source_bytes > max_source_bytes:
    raise SystemExit(f"Europe PMC source bytes exceed cap: {source_bytes} > {max_source_bytes}")

inventory = {
    "dataset_id": "europe_pmc_search",
    "query": os.environ["QUERY"],
    "start_date": os.environ["START_DATE"],
    "end_date": os.environ["END_DATE"],
    "page_count": len(records),
    "raw_records": raw_records,
    "unique_records": len(seen_keys),
    "duplicate_records": len(duplicate_keys),
    "source_bytes": source_bytes,
    "records": records,
}
inventory_json.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    f"semantic_validation=downloaded pages={len(records)} raw_records={raw_records} "
    f"unique_records={len(seen_keys)} duplicate_records={len(duplicate_keys)} source_bytes={source_bytes}"
)
PY

echo "new_fetches=$new_fetches"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
