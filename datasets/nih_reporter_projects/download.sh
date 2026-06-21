#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nih_reporter_projects"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$PAGE_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

# NIH RePORTER caps offset+limit at 15000 per query, so we sample one fiscal year
# per criteria (each year is an independent cohort = one sample per field).
START_YEAR="${NIH_START_YEAR:-2010}"
END_YEAR="${NIH_END_YEAR:-2024}"
LIMIT="${NIH_LIMIT:-500}"
WINDOW_CAP="${NIH_WINDOW_CAP:-14500}"
REQUEST_DELAY="${NIH_REQUEST_DELAY_SECONDS:-0.7}"
MIN_RECORDS="${NIH_MIN_RECORDS:-100000}"
URL="https://api.reporter.nih.gov/v2/projects/search"

echo "[$(date -Is)] download_start dataset=$DATASET_ID years=${START_YEAR}-${END_YEAR} limit=$LIMIT window_cap=$WINDOW_CAP"

year="$START_YEAR"
while [ "$year" -le "$END_YEAR" ]; do
  offset=0
  page=0
  while [ $(( offset + LIMIT )) -le "$WINDOW_CAP" ]; do
    out="$PAGE_DIR/nih_${year}_p$(printf '%03d' "$page").json"
    tmp="$out.tmp"
    if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
      page_rows="$(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['results']))" "$out")"
      echo "cache_hit year=$year page=$page rows=$page_rows"
    else
      rm -f "$tmp"
      # include_fields uses PascalCase names; the response keys come back snake_case.
      body="{\"criteria\":{\"fiscal_years\":[${year}]},\"include_fields\":[\"ApplId\",\"AwardAmount\",\"DirectCostAmt\",\"IndirectCostAmt\",\"ProjectStartDate\",\"ProjectEndDate\",\"AwardNoticeDate\"],\"offset\":${offset},\"limit\":${LIMIT},\"sort_field\":\"project_start_date\",\"sort_order\":\"desc\"}"
      curl --globoff -fL --retry 4 --retry-delay 3 \
        -A "openzl-public-datasets/1.0" \
        -H "Content-Type: application/json" \
        -X POST --data "$body" \
        -o "$tmp" "$URL"
      page_rows="$(python3 - <<'PY' "$tmp" "$year" "$page"
import json
import sys

path, year, page = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, encoding="utf-8") as fh:
    obj = json.load(fh)
res = obj.get("results")
if not isinstance(res, list):
    raise SystemExit(f"bad NIH payload year={year} page={page}: missing results")
if res and len(res[0]) > 15:
    raise SystemExit(
        f"include_fields not applied (record has {len(res[0])} keys) year={year} page={page}; "
        "check the PascalCase field names before downloading full records"
    )
print(len(res))
PY
)"
      mv "$tmp" "$out"
      sleep "$REQUEST_DELAY"
    fi
    echo "page_done year=$year page=$page offset=$offset rows=$page_rows"
    if [ "$page_rows" -eq 0 ] || [ "$page_rows" -lt "$LIMIT" ]; then
      break
    fi
    offset=$(( offset + LIMIT ))
    page=$(( page + 1 ))
  done
  year=$(( year + 1 ))
done

python3 - <<'PY' "$PAGE_DIR" "$DOWNLOAD_DIR/download_stats.json" "$MIN_RECORDS"
import json
import re
import sys
from pathlib import Path

page_dir = Path(sys.argv[1])
stats_path = Path(sys.argv[2])
min_records = int(sys.argv[3])
page_re = re.compile(r"nih_(\d{4})_p\d+\.json$")
per_year = {}
seen = set()
duplicate = 0
rows_total = 0
for path in sorted(page_dir.glob("nih_*_p*.json")):
    match = page_re.search(path.name)
    if not match:
        continue
    year = int(match.group(1))
    with path.open(encoding="utf-8") as fh:
        results = json.load(fh)["results"]
    rows_total += len(results)
    per_year[year] = per_year.get(year, 0) + len(results)
    for row in results:
        aid = row.get("appl_id")
        if aid in seen:
            duplicate += 1
        elif aid is not None:
            seen.add(aid)

unique = len(seen)
if rows_total < min_records:
    raise SystemExit(f"downloaded only {rows_total} rows, minimum is {min_records}")

stats = {
    "dataset_id": "nih_reporter_projects",
    "rows_total": rows_total,
    "unique_ids": unique,
    "duplicate_ids": duplicate,
    "per_year": {str(k): per_year[k] for k in sorted(per_year)},
    "min_records": min_records,
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"years={len(per_year)} rows_total={rows_total} unique={unique} duplicate={duplicate}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
