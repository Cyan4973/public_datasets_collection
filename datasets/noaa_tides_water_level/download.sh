#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=noaa_tides_water_level
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"

RUN_TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAIL_TSV="$DOWNLOAD_DIR/download_failures.tsv"
PLAN_TSV="$DOWNLOAD_DIR/download_plan.tsv"
CHECKSUM_FILE="$DOWNLOAD_DIR/collection_checksums.sha256"
: > "$FAIL_TSV"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

START_DATE="${NOAA_TIDES_START_DATE:-2023-01-01}"
END_DATE="${NOAA_TIDES_END_DATE:-2024-12-31}"
BASE_URL="https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

log() { printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"; }

log "download_start dataset=$DATASET_ID start_date=$START_DATE end_date=$END_DATE"

python3 - <<'PY' "$PLAN_TSV" "$START_DATE" "$END_DATE" "$BASE_URL"
from __future__ import annotations

import calendar
import datetime as dt
import sys
import urllib.parse
from pathlib import Path

plan_path = Path(sys.argv[1])
start = dt.date.fromisoformat(sys.argv[2])
end = dt.date.fromisoformat(sys.argv[3])
base_url = sys.argv[4]

stations = [
    ("8418150", "Portland_ME"),
    ("8443970", "Boston_MA"),
    ("8518750", "The_Battery_NY"),
    ("8534720", "Atlantic_City_NJ"),
    ("8638610", "Sewells_Point_VA"),
    ("8665530", "Charleston_SC"),
    ("8720218", "Mayport_FL"),
    ("8724580", "Key_West_FL"),
    ("8729840", "Pensacola_FL"),
    ("8735180", "Dauphin_Island_AL"),
    ("8761724", "Grand_Isle_LA"),
    ("8771450", "Galveston_Pier_21_TX"),
    ("8779770", "Port_Isabel_TX"),
    ("9410170", "San_Diego_CA"),
    ("9410660", "Los_Angeles_CA"),
    ("9414290", "San_Francisco_CA"),
    ("9439040", "Astoria_OR"),
    ("9447130", "Seattle_WA"),
    ("9450460", "Ketchikan_AK"),
    ("9455920", "Anchorage_AK"),
    ("1612340", "Honolulu_HI"),
]

def month_starts(first: dt.date, last: dt.date):
    current = first.replace(day=1)
    while current <= last:
        yield current
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

with plan_path.open("w", encoding="utf-8", newline="") as fh:
    fh.write("station_id\tstation_name\tbegin_date\tend_date\turl\trel_out\n")
    for station_id, station_name in stations:
        for month_start in month_starts(start, end):
            month_last = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])
            begin = max(start, month_start)
            finish = min(end, month_last)
            if begin > finish:
                continue
            params = {
                "product": "water_level",
                "application": "openzl",
                "begin_date": begin.strftime("%Y%m%d"),
                "end_date": finish.strftime("%Y%m%d"),
                "station": station_id,
                "datum": "MSL",
                "time_zone": "gmt",
                "units": "metric",
                "format": "json",
            }
            url = base_url + "?" + urllib.parse.urlencode(params)
            rel_out = f"station_{station_id}_{begin:%Y%m%d}_{finish:%Y%m%d}.json"
            fh.write(f"{station_id}\t{station_name}\t{begin}\t{finish}\t{url}\t{rel_out}\n")
PY

validate_payload() {
  path=$1
  python3 - <<'PY' "$path" >>"$LOG_FILE" 2>&1
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
obj = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
    raise SystemExit(f"missing data list in {path}")
if not obj["data"]:
    raise SystemExit(f"empty data list in {path}")
PY
}

fetch() {
  url=$1
  out=$2
  tmp="${out}.tmp"
  if [[ "${FORCE_DOWNLOAD:-0}" != "1" && -s "$out" ]]; then
    validate_payload "$out"
    return 2
  fi
  rm -f "$tmp"
  curl --globoff -L --fail --retry 3 --retry-delay 5 \
    -A 'openzl-public-datasets/1.0' \
    -o "$tmp" "$url"
  validate_payload "$tmp"
  mv "$tmp" "$out"
  return 0
}

success_count=0
cached_count=0
failure_count=0
while IFS=$'\t' read -r station_id station_name begin_date end_date url rel_out; do
  [[ "$station_id" != "station_id" ]] || continue
  [[ -n "$station_id" ]] || continue
  out="$DOWNLOAD_DIR/$rel_out"
  log "fetch station=$station_id station_name=$station_name begin=$begin_date end=$end_date"
  if fetch "$url" "$out"; then
    success_count=$((success_count + 1))
  else
    status=$?
    if [ "$status" -eq 2 ]; then
      cached_count=$((cached_count + 1))
    else
      failure_count=$((failure_count + 1))
      rm -f "$out" "$out.tmp"
      printf '%s\t%s\t%s\t%s\t%s\n' "$station_id" "$begin_date" "$end_date" "$rel_out" "$url" >> "$FAIL_TSV"
      log "failed station=$station_id begin=$begin_date end=$end_date"
    fi
  fi
done < "$PLAN_TSV"

tail -n +2 "$PLAN_TSV" | while IFS=$'\t' read -r station_id station_name begin_date end_date url rel_out; do
  [[ -n "$station_id" ]] || continue
  if [ -f "$DOWNLOAD_DIR/$rel_out" ]; then
    sha256sum "$DOWNLOAD_DIR/$rel_out"
  fi
done > "$CHECKSUM_FILE"

log "success_count=$success_count cached_count=$cached_count failure_count=$failure_count"
log "plan_file=$PLAN_TSV failures_file=$FAIL_TSV checksum_file=$CHECKSUM_FILE"
if [ "$failure_count" -gt 0 ]; then
  log "download completed with failures"
  exit 1
fi
log "download done dataset=$DATASET_ID"
