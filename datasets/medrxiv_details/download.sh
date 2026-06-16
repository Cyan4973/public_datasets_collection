#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="medrxiv_details"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

MEDRXIV_YEAR="${MEDRXIV_YEAR:-2024}"
REQUEST_DELAY="${MEDRXIV_REQUEST_DELAY:-1}"
MIN_RECORDS="${MIN_RECORDS:-10000}"
MAX_SOURCE_BYTES="${MAX_SOURCE_BYTES:-250000000}"
WINDOWS_TSV="$DOWNLOAD_DIR/windows.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
INVENTORY_TSV="$DOWNLOAD_DIR/download_inventory.tsv"
INVENTORY_JSON="$DOWNLOAD_DIR/download_inventory.json"

export MEDRXIV_YEAR WINDOWS_TSV
python3 - <<'PY'
from __future__ import annotations

import calendar
import os
from pathlib import Path

year = int(os.environ["MEDRXIV_YEAR"])
out = Path(os.environ["WINDOWS_TSV"])
with out.open("w", encoding="utf-8") as fh:
    fh.write("window_id\tstart_date\tend_date\n")
    for month in range(1, 13):
        last_day = calendar.monthrange(year, month)[1]
        fh.write(f"{year}_{month:02d}\t{year}-{month:02d}-01\t{year}-{month:02d}-{last_day:02d}\n")
PY

printf "local_name\turl\twindow_id\tstart_date\tend_date\tcursor\n" > "$PLAN"
printf "local_name\twindow_id\tstart_date\tend_date\tcursor\tcount\ttotal\tcount_new_papers\tsource_bytes\n" > "$INVENTORY_TSV"

validate_page() {
  local path="$1"
  python3 - "$path" <<'PY'
from __future__ import annotations

import json
import sys

path = sys.argv[1]
obj = json.load(open(path, encoding="utf-8"))
messages = obj.get("messages")
collection = obj.get("collection")
if not isinstance(messages, list) or not messages or not isinstance(collection, list):
    raise SystemExit(f"bad medRxiv payload: {path}")
message = messages[0]
if message.get("status") != "ok":
    raise SystemExit(f"medRxiv status not ok in {path}: {message.get('status')}")
count = int(message.get("count", len(collection)))
total = int(message.get("total", 0))
new_papers = int(message.get("count_new_papers", 0))
if count != len(collection):
    raise SystemExit(f"medRxiv count mismatch in {path}: message={count} collection={len(collection)}")
print(f"{count}\t{total}\t{new_papers}")
PY
}

downloaded_total=0
new_fetches=0
while IFS=$'\t' read -r window_id start_date end_date; do
  [[ "$window_id" != "window_id" ]] || continue
  cursor=0
  total=-1
  while (( total < 0 || cursor < total )); do
    local_name="${window_id}_cursor$(printf '%06d' "$cursor").json"
    url="https://api.medrxiv.org/details/medrxiv/${start_date}/${end_date}/${cursor}"
    target="$DOWNLOAD_DIR/$local_name"
    printf "%s\t%s\t%s\t%s\t%s\t%s\n" "$local_name" "$url" "$window_id" "$start_date" "$end_date" "$cursor" >> "$PLAN"
    if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
      echo "cache_hit window=$window_id cursor=$cursor path=$target"
    else
      tmp="$target.tmp"
      rm -f "$tmp"
      echo "fetch window=$window_id cursor=$cursor"
      curl --globoff -fL --retry 3 --retry-delay 5 -A "openzl-public-datasets/1.0" -o "$tmp" "$url"
      mv "$tmp" "$target"
      new_fetches=$((new_fetches + 1))
      if [[ "$REQUEST_DELAY" != "0" ]]; then
        sleep "$REQUEST_DELAY"
      fi
    fi
    page_info="$(validate_page "$target")"
    IFS=$'\t' read -r count total new_papers <<< "$page_info"
    size="$(wc -c < "$target")"
    downloaded_total=$((downloaded_total + size))
    if (( downloaded_total > MAX_SOURCE_BYTES )); then
      echo "downloaded source bytes exceed cap: $downloaded_total > $MAX_SOURCE_BYTES" >&2
      exit 1
    fi
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
      "$local_name" "$window_id" "$start_date" "$end_date" "$cursor" "$count" "$total" "$new_papers" "$size" >> "$INVENTORY_TSV"
    if (( count == 0 )); then
      break
    fi
    cursor=$((cursor + count))
  done
done < "$WINDOWS_TSV"

export DOWNLOAD_DIR INVENTORY_TSV INVENTORY_JSON MIN_RECORDS MAX_SOURCE_BYTES MEDRXIV_YEAR
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
year = int(os.environ["MEDRXIV_YEAR"])

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
        for item in obj.get("collection", []):
            doi = str(item.get("doi", "")).strip()
            version = str(item.get("version", "")).strip()
            if not doi or not version:
                continue
            key = (doi, version)
            if key in seen_keys:
                duplicate_keys.add(key)
            seen_keys.add(key)
            keys.append(key)
        count = len(keys)
        raw_records += count
        size = int(row["source_bytes"])
        source_bytes += size
        records.append({**row, "source_bytes": size, "record_count": count})

if len(seen_keys) < min_records:
    raise SystemExit(f"medRxiv download below repair floor: records={len(seen_keys)} < {min_records}")
if source_bytes > max_source_bytes:
    raise SystemExit(f"medRxiv source bytes exceed cap: {source_bytes} > {max_source_bytes}")

inventory = {
    "dataset_id": "medrxiv_details",
    "medrxiv_year": year,
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
