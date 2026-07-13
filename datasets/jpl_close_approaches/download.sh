#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="jpl_close_approaches"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

# Walk the close-approach table one decade per request (the API computes approaches over any window).
START_DECADE="${JPL_START_DECADE:-1900}"
END_DECADE="${JPL_END_DECADE:-2090}"
REQUEST_DELAY="${JPL_REQUEST_DELAY_SECONDS:-1.0}"
MIN_RECORDS="${JPL_MIN_RECORDS:-35000}"
BASE_URL="https://ssd-api.jpl.nasa.gov/cad.api"

echo "[$(date -Is)] download_start dataset=$DATASET_ID decades=${START_DECADE}-${END_DECADE}"

decade="$START_DECADE"
while [ "$decade" -le "$END_DECADE" ]; do
  dmin="${decade}-01-01"
  dmax="$(( decade + 9 ))-12-31"
  out="$PAGE_DIR/cad_${decade}.json"
  tmp="$out.tmp"
  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit decade=$decade path=$out"
  else
    rm -f "$tmp"
    url="${BASE_URL}?date-min=${dmin}&date-max=${dmax}&sort=date&fullname=true"
    echo "fetch decade=$decade url=$url"
    curl --globoff -fL --retry 3 --retry-delay 3 -A "openzl-public-datasets/1.0" -o "$tmp" "$url"
    python3 - <<'PY' "$tmp" "$decade"
import json
import sys

path, decade = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    obj = json.load(fh)
if not isinstance(obj, dict):
    raise SystemExit(f"bad CAD payload for decade {decade}: not an object")
count = int(obj.get("count") or 0)
if count > 0 and ("fields" not in obj or "data" not in obj):
    raise SystemExit(f"CAD payload for decade {decade} missing fields/data despite count={count}")
PY
    mv "$tmp" "$out"
    sleep "$REQUEST_DELAY"
  fi
  decade=$(( decade + 10 ))
done

python3 - <<'PY' "$PAGE_DIR" "$DOWNLOAD_DIR/download_stats.json" "$MIN_RECORDS"
import json
import re
import sys
from pathlib import Path

page_dir = Path(sys.argv[1])
stats_path = Path(sys.argv[2])
min_records = int(sys.argv[3])
page_re = re.compile(r"cad_(\d{4})\.json$")
pages = []
rows_total = 0
for path in sorted(page_dir.glob("cad_*.json")):
    match = page_re.search(path.name)
    if not match:
        continue
    with path.open(encoding="utf-8") as fh:
        obj = json.load(fh)
    n = len(obj.get("data") or [])
    rows_total += n
    pages.append({"path": path.name, "decade": int(match.group(1)), "rows": n})

if rows_total < min_records:
    raise SystemExit(f"only {rows_total} close approaches downloaded, need {min_records}")

stats = {
    "dataset_id": "jpl_close_approaches",
    "pages": pages,
    "rows_total": rows_total,
    "min_records": min_records,
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"decades={len(pages)} rows_total={rows_total}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
