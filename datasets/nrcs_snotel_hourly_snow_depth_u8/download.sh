#!/usr/bin/env bash
# Fetch one NRCS reportGenerator hourly SNWD CSV (WY2022-WY2024) per pinned
# SNOTEL (SNTL) station. Network I/O is curl only; Python only validates.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nrcs_snotel_hourly_snow_depth_u8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
HOURLY_DIR="$DOWNLOAD_DIR/hourly"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
STATIONS="$RECIPE_DIR/sntl_stations_20261009.csv"
STATIONS_SHA256="c6af534ef2168d7900ce038b4b059d479e6e33cc35a521d5c2092f979517c6b4"
CHECKER="$RECIPE_DIR/scripts/snotel_snwd.py"
BASE="https://wcc.sc.egov.usda.gov/reportGenerator/view_csv"
RANGE="2021-10-01,2024-09-30"
UA="openzl-public-datasets-snotel-download/1.0"
SLEEP_SECONDS="${SNOTEL_SLEEP_SECONDS:-1}"
MIN_DATA_STATIONS=500

mkdir -p "$HOURLY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

actual="$(sha256sum "$STATIONS" | awk '{print $1}')"
[[ "$actual" == "$STATIONS_SHA256" ]] || { echo "pinned station list changed: $actual" >&2; exit 1; }
[[ "$(head -n 1 "$STATIONS")" == "Station Id,State Code,Elevation" ]] || { echo "bad station list header" >&2; exit 1; }

fetch() {  # url target
  curl --globoff --fail --silent --show-error --location \
    --retry 5 --retry-delay 5 --retry-all-errors --connect-timeout 30 --max-time 600 \
    --max-filesize 20000000 --speed-limit 1024 --speed-time 120 \
    --user-agent "$UA" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

# Live station list, for provenance only: the recipe scope is the pinned list.
live="$DOWNLOAD_DIR/sntl_stations_live.csv"
if fetch "$BASE/customMultipleStationReport/daily/start_of_period/network=%22SNTL%22%7Cname/0,0/stationId,state.code,elevation" "$live"; then
  live_n="$(grep -v '^#' "$live" | tail -n +2 | wc -l)"
  added="$(comm -13 <(tail -n +2 "$STATIONS" | cut -d, -f1,2 | sort) <(grep -v '^#' "$live" | tail -n +2 | cut -d, -f1,2 | sort) | wc -l)"
  removed="$(comm -23 <(tail -n +2 "$STATIONS" | cut -d, -f1,2 | sort) <(grep -v '^#' "$live" | tail -n +2 | cut -d, -f1,2 | sort) | wc -l)"
  echo "live_station_list stations=$live_n added_vs_pinned=$added removed_vs_pinned=$removed"
else
  echo "warning: live station list fetch failed (pinned list is authoritative)"
fi

plan_tmp="$DOWNLOAD_DIR/download_plan.tsv.tmp"
printf 'station_id\tstate\televation\tstatus\trows\tbytes\tsha256\tfile\turl\n' > "$plan_tmp"
n=0; n_data=0; n_nodata=0; n_cached=0; bytes_total=0
while IFS=, read -r sid state elev; do
  [[ "$sid" == "Station Id" ]] && continue
  [[ "$sid" =~ ^[0-9]+$ && "$state" =~ ^[A-Z]{2}$ ]] || { echo "bad station row: $sid,$state" >&2; exit 1; }
  n=$((n + 1))
  file="${sid}_${state}.csv"
  target="$HOURLY_DIR/$file"
  url="$BASE/customSingleStationReport/hourly/start_of_period/${sid}:${state}:SNTL%7Cid=%22%22%7Cname/${RANGE}/SNWD::value"
  result=""
  if [[ -s "$target" ]]; then
    if result="$(python3 -I "$CHECKER" check "$target" "$sid" "$state")"; then
      n_cached=$((n_cached + 1))
    else
      echo "cached file invalid ($result), refetching $file"
      rm -f "$target"; result=""
    fi
  fi
  attempt=0
  while [[ -z "$result" ]]; do
    attempt=$((attempt + 1))
    fetch "$url" "$target"
    sleep "$SLEEP_SECONDS"
    if result="$(python3 -I "$CHECKER" check "$target" "$sid" "$state")"; then
      break
    fi
    echo "invalid payload station=$sid:$state attempt=$attempt: $result"
    mv "$target" "$LOG_DIR/rejected_${file}.$attempt"
    result=""
    if (( attempt >= 3 )); then
      echo "station $sid:$state returned an invalid payload 3 times; aborting" >&2
      exit 1
    fi
    sleep 30
  done
  status="${result%% *}"
  rows=0
  [[ "$status" == "data" ]] && rows="${result#* }"
  size="$(stat -c %s "$target")"
  sha="$(sha256sum "$target" | awk '{print $1}')"
  if [[ "$status" == "data" ]]; then n_data=$((n_data + 1)); else n_nodata=$((n_nodata + 1)); echo "skip station=$sid:$state no hourly SNWD in range"; fi
  bytes_total=$((bytes_total + size))
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$sid" "$state" "$elev" "$status" "$rows" "$size" "$sha" "$file" "$url" >> "$plan_tmp"
  if (( n % 50 == 0 )); then
    echo "[$(date -Is)] progress stations=$n data=$n_data nodata=$n_nodata cached=$n_cached bytes=$bytes_total"
  fi
done < "$STATIONS"

[[ "$n" -eq 934 ]] || { echo "expected 934 pinned stations, saw $n" >&2; exit 1; }
(( n_data >= MIN_DATA_STATIONS )) || { echo "only $n_data stations returned hourly SNWD (< $MIN_DATA_STATIONS); source likely blocked" >&2; exit 1; }
mv "$plan_tmp" "$DOWNLOAD_DIR/download_plan.tsv"
echo "[$(date -Is)] download done dataset=$DATASET_ID stations=$n data=$n_data nodata=$n_nodata cached=$n_cached bytes=$bytes_total"
