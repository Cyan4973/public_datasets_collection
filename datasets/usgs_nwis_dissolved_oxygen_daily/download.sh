#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_nwis_dissolved_oxygen_daily"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
mkdir -p "$LOG_DIR" "$PAGE_DIR"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

PARAMETER_CD="00300"
STAT_CD="00003"
START_DATE="${USGS_NWIS_DISSOLVED_OXYGEN_START_DATE:-2000-01-01}"
END_DATE="${USGS_NWIS_DISSOLVED_OXYGEN_END_DATE:-2024-12-31}"
STATES="${USGS_NWIS_DISSOLVED_OXYGEN_STATES:-al ak az ca co fl ga ia in ma md mi nc nd ne ny or pa ri sc tx ut va wa wi wy}"
MIN_VALUES_PER_SAMPLE="${USGS_NWIS_DISSOLVED_OXYGEN_MIN_VALUES_PER_SAMPLE:-7000}"
MIN_SAMPLE_COUNT="${USGS_NWIS_DISSOLVED_OXYGEN_MIN_SAMPLE_COUNT:-20}"
REQUEST_DELAY="${USGS_NWIS_DISSOLVED_OXYGEN_REQUEST_DELAY_SECONDS:-1.0}"
BASE_URL="https://waterservices.usgs.gov/nwis/dv/"
FAILURES_FILE="$DOWNLOAD_DIR/download_failures.tsv"
PLAN_FILE="$DOWNLOAD_DIR/download_plan.tsv"
SELECTED_FILE="$DOWNLOAD_DIR/selected_sites.tsv"
STATS_FILE="$DOWNLOAD_DIR/download_stats.json"
CHECKSUM_FILE="$DOWNLOAD_DIR/collection_checksums.sha256"

: > "$FAILURES_FILE"
printf 'state_code\tstart_date\tend_date\turl\trel_out\n' > "$PLAN_FILE"

echo "[$(date -Is)] download_start dataset=$DATASET_ID states='$STATES' parameter=$PARAMETER_CD stat=$STAT_CD window=$START_DATE..$END_DATE min_values=$MIN_VALUES_PER_SAMPLE"

for state in $STATES; do
  state_lc="$(printf '%s' "$state" | tr '[:upper:]' '[:lower:]')"
  rel_out="pages/usgs_${PARAMETER_CD}_${state_lc}.json"
  out="$DOWNLOAD_DIR/$rel_out"
  tmp="$out.tmp"
  url="${BASE_URL}?format=json&stateCd=${state_lc}&parameterCd=${PARAMETER_CD}&statCd=${STAT_CD}&startDT=${START_DATE}&endDT=${END_DATE}&siteStatus=all"
  printf '%s\t%s\t%s\t%s\t%s\n' "$state_lc" "$START_DATE" "$END_DATE" "$url" "$rel_out" >> "$PLAN_FILE"

  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit state=$state_lc path=$out"
    continue
  fi

  rm -f "$tmp"
  echo "fetch state=$state_lc url=$url"
  if ! curl --globoff -fL --retry 3 --retry-delay 5 -A "openzl-public-datasets/1.0" -o "$tmp" "$url"; then
    printf 'state\t%s\t%s\n' "$state_lc" "$url" >> "$FAILURES_FILE"
    echo "failed state=$state_lc"
    rm -f "$tmp"
    continue
  fi

  if ! python3 - "$tmp" "$PARAMETER_CD" "$STAT_CD" <<'PY'; then
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
parameter_cd = sys.argv[2]
stat_cd = sys.argv[3]
payload = json.loads(path.read_text(encoding="utf-8"))
time_series = payload.get("value", {}).get("timeSeries", [])
if not isinstance(time_series, list):
    raise SystemExit(f"missing timeSeries in {path}")
for ts in time_series:
    if not isinstance(ts, dict):
        continue
    name = str(ts.get("name", ""))
    if f":{parameter_cd}:" in name and name.endswith(f":{stat_cd}"):
        break
else:
    # Empty but structurally valid state pages are accepted; the build will
    # reject the collection if too few long site series are present.
    if time_series:
        raise SystemExit(f"no matching {parameter_cd}:{stat_cd} series in {path}")
PY
    printf 'state\t%s\tinvalid_payload\n' "$state_lc" >> "$FAILURES_FILE"
    echo "invalid state=$state_lc"
    rm -f "$tmp"
    continue
  fi

  mv "$tmp" "$out"
  sleep "$REQUEST_DELAY"
done

python3 - "$PAGE_DIR" "$SELECTED_FILE" "$STATS_FILE" "$MIN_VALUES_PER_SAMPLE" "$MIN_SAMPLE_COUNT" "$PARAMETER_CD" "$STAT_CD" <<'PY'
from __future__ import annotations

import csv
import json
import math
import re
import sys
from pathlib import Path

page_dir = Path(sys.argv[1])
selected_path = Path(sys.argv[2])
stats_path = Path(sys.argv[3])
min_values = int(sys.argv[4])
min_samples = int(sys.argv[5])
parameter_cd = sys.argv[6]
stat_cd = sys.argv[7]
page_re = re.compile(r"usgs_(\d{5})_([a-z]{2})\.json$")

def parse_row(row: object) -> tuple[float, str] | None:
    if not isinstance(row, dict):
        return None
    raw_value = str(row.get("value", "")).strip()
    raw_date = str(row.get("dateTime", "")).strip()
    if raw_value == "" or raw_date == "":
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0:
        return None
    date_part = raw_date[:10]
    pieces = date_part.split("-")
    if len(pieces) != 3:
        return None
    try:
        year, month, day = (int(piece) for piece in pieces)
    except ValueError:
        return None
    if year < 0 or year > 65535 or month < 1 or month > 12 or day < 1 or day > 31:
        return None
    return value, date_part

pages = []
selected_rows = []
candidate_count = 0
for path in sorted(page_dir.glob(f"usgs_{parameter_cd}_*.json")):
    match = page_re.search(path.name)
    if not match:
        continue
    state = match.group(2)
    payload = json.loads(path.read_text(encoding="utf-8"))
    series_count = 0
    long_series_count = 0
    for ts in payload.get("value", {}).get("timeSeries", []):
        if not isinstance(ts, dict):
            continue
        name = str(ts.get("name", ""))
        if f":{parameter_cd}:" not in name or not name.endswith(f":{stat_cd}"):
            continue
        source_info = ts.get("sourceInfo", {})
        site_codes = source_info.get("siteCode", []) if isinstance(source_info, dict) else []
        site_no = ""
        if site_codes and isinstance(site_codes[0], dict):
            site_no = str(site_codes[0].get("value", "")).strip()
        if not site_no:
            continue
        best_count = 0
        first_date = ""
        last_date = ""
        for wrapper in ts.get("values", []):
            if not isinstance(wrapper, dict):
                continue
            rows = wrapper.get("value", [])
            if not isinstance(rows, list):
                continue
            count = 0
            wrapper_first = ""
            wrapper_last = ""
            for row in rows:
                parsed = parse_row(row)
                if parsed is None:
                    continue
                _, date_part = parsed
                count += 1
                if wrapper_first == "":
                    wrapper_first = date_part
                wrapper_last = date_part
            if count > best_count:
                best_count = count
                first_date = wrapper_first
                last_date = wrapper_last
        series_count += 1
        candidate_count += 1
        if best_count >= min_values:
            long_series_count += 1
            selected_rows.append((state, site_no, best_count, first_date, last_date, name, path.name))
    pages.append({"path": path.name, "state": state, "series": series_count, "long_series": long_series_count})

selected_rows.sort(key=lambda row: (row[0], row[1]))
with selected_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["state_code", "site_no", "value_count", "start_date", "end_date", "series_name", "page"])
    writer.writerows(selected_rows)

stats = {
    "candidate_site_series": candidate_count,
    "dataset_id": "usgs_nwis_dissolved_oxygen_daily",
    "min_sample_count": min_samples,
    "min_values_per_sample": min_values,
    "pages": pages,
    "selected_site_series": len(selected_rows),
}
stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
if len(selected_rows) < min_samples:
    raise SystemExit(f"only {len(selected_rows)} long site series, minimum is {min_samples}")
print(f"pages={len(pages)} candidate_series={candidate_count} selected_series={len(selected_rows)}")
PY

if [ -s "$FAILURES_FILE" ]; then
  echo "download failures recorded in $FAILURES_FILE"
  exit 1
fi

find "$PAGE_DIR" -maxdepth 1 -type f -name "usgs_${PARAMETER_CD}_*.json" -print0 | sort -z | xargs -0 sha256sum > "$CHECKSUM_FILE"

echo "selected_file=$SELECTED_FILE"
echo "stats_file=$STATS_FILE"
echo "checksum_file=$CHECKSUM_FILE"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
