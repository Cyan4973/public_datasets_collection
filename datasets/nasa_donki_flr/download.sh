#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_donki_flr"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

START_YEAR="${DONKI_START_YEAR:-2010}"
END_YEAR="${DONKI_END_YEAR:-2026}"
REQUEST_DELAY="${DONKI_REQUEST_DELAY_SECONDS:-1.0}"
MIN_RECORDS="${DONKI_MIN_RECORDS:-3000}"
BASE_URL="https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/FLR"

echo "[$(date -Is)] download_start dataset=$DATASET_ID years=${START_YEAR}-${END_YEAR}"

year="$START_YEAR"
while [ "$year" -le "$END_YEAR" ]; do
  out="$PAGE_DIR/flr_${year}.json"
  tmp="$out.tmp"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit year=$year path=$out"
  else
    rm -f "$tmp"
    url="${BASE_URL}?startDate=${year}-01-01&endDate=${year}-12-31"
    echo "fetch year=$year url=$url"
    curl --globoff -fL --retry 3 --retry-delay 3 -A "openzl-public-datasets/1.0" -o "$tmp" "$url"
    python3 - <<'PY' "$tmp" "$year"
import json
import sys

path, year = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    obj = json.load(fh)
if not isinstance(obj, list):
    raise SystemExit(f"bad DONKI FLR payload for {year}: expected JSON array")
PY
    mv "$tmp" "$out"
    sleep "$REQUEST_DELAY"
  fi
  year=$(( year + 1 ))
done

python3 - <<'PY' "$PAGE_DIR" "$DOWNLOAD_DIR/download_stats.json" "$MIN_RECORDS" "$START_YEAR" "$END_YEAR"
import json
import re
import sys
from pathlib import Path

page_dir = Path(sys.argv[1])
stats_path = Path(sys.argv[2])
min_records = int(sys.argv[3])
start_year, end_year = sys.argv[4], sys.argv[5]
page_re = re.compile(r"flr_(\d{4})\.json$")
pages = []
seen = set()
duplicate = 0
rows_total = 0
for path in sorted(page_dir.glob("flr_*.json")):
    match = page_re.search(path.name)
    if not match:
        continue
    with path.open(encoding="utf-8") as fh:
        obj = json.load(fh)
    rows_total += len(obj)
    for row in obj:
        fid = row.get("flrID")
        if fid in seen:
            duplicate += 1
        elif fid:
            seen.add(fid)
    pages.append({"path": path.name, "year": int(match.group(1)), "rows": len(obj)})

unique = len(seen)
if unique < min_records:
    raise SystemExit(f"only {unique} unique FLR records over {start_year}-{end_year}, need {min_records}")

stats = {
    "dataset_id": "nasa_donki_flr",
    "pages": pages,
    "rows_total": rows_total,
    "unique_ids": unique,
    "duplicate_ids": duplicate,
    "start_year": int(start_year),
    "end_year": int(end_year),
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"years={start_year}-{end_year} pages={len(pages)} rows_total={rows_total} unique={unique}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
