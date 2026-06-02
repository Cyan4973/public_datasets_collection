#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="seismic_waveform_i32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAILURES_FILE="$DOWNLOAD_DIR/download_failures.tsv"
PLAN_PATH="$DOWNLOAD_DIR/download_plan.tsv"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
printf 'name\tstatus\tdetail\n' > "$FAILURES_FILE"
printf 'name\tparams\tstart\tduration_seconds\texpected_samples\turl\n' > "$PLAN_PATH"

BASE_URL="https://service.iris.edu/irisws/timeseries/1/query"
declare -a QUERIES=(
  "net=IU&sta=COLA&loc=00&cha=BHZ|2018-11-30T17:29:00|600|anchorage_cola|24000"
  "net=IU&sta=HRV&loc=00&cha=BHZ|2010-02-27T06:34:00|600|chile_hrv|12000"
  "net=IU&sta=HRV&loc=00&cha=BHZ|2021-08-14T12:29:00|600|haiti_hrv|12000"
  "net=IU&sta=MAJO&loc=00&cha=BHZ|2016-04-15T16:25:00|600|kumamoto_majo|12000"
  "net=IU&sta=ANMO&loc=00&cha=BHZ|2017-09-19T18:14:00|600|mexico_anmo|12000"
  "net=IU&sta=TUC&loc=00&cha=BHZ|2015-04-25T06:11:00|600|nepal_tuc|12000"
  "net=IU&sta=SNZO&loc=00&cha=BHZ|2016-11-13T11:02:00|600|nz_snzo|12000"
  "net=IU&sta=COLA&loc=00&cha=BHZ|2013-05-24T05:44:00|600|okhotsk_cola|12000"
  "net=IU&sta=ANMO&loc=00&cha=BHZ|2023-06-15T12:00:00|600|quiet_anmo|24000"
  "net=IU&sta=COLA&loc=00&cha=BHZ|2004-12-26T00:58:00|600|sumatra_cola|12000"
  "net=IU&sta=ANMO&loc=00&cha=BHZ|2011-03-11T05:46:00|600|tohoku_anmo|12000"
  "net=IU&sta=KEV&loc=00&cha=BHZ|2023-02-06T01:17:00|600|turkey_kev|12000"
)

sample_count_for_file() {
  awk 'BEGIN { n=0 } /^TIMESERIES/ { next } NF { n++ } END { print n }' "$1"
}

valid_ascii_file() {
  local path="$1" expected="$2" parsed
  [[ -s "$path" ]] || return 1
  grep -q '^TIMESERIES ' "$path" || return 1
  parsed="$(sample_count_for_file "$path")"
  [[ "$parsed" == "$expected" ]]
}

fetch_url() {
  local url="$1" out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -L --fail --show-error --retry 3 --retry-delay 2 -o "$out" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$out" "$url"
  else
    return 127
  fi
}

for entry in "${QUERIES[@]}"; do
  IFS='|' read -r params start duration name expected_samples <<< "$entry"
  outfile="$DOWNLOAD_DIR/${name}.ascii"
  url="${BASE_URL}?${params}&starttime=${start}&duration=${duration}&output=ascii"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$params" "$start" "$duration" "$expected_samples" "$url" >> "$PLAN_PATH"

  if valid_ascii_file "$outfile" "$expected_samples"; then
    echo "cached name=$name file=$outfile"
    continue
  fi

  rm -f "$outfile" "$outfile.tmp"
  echo "downloading name=$name url=$url"
  if ! fetch_url "$url" "$outfile.tmp"; then
    printf '%s\tfailed\tfetch_failed\n' "$name" >> "$FAILURES_FILE"
    rm -f "$outfile.tmp"
    continue
  fi
  mv "$outfile.tmp" "$outfile"

  if ! valid_ascii_file "$outfile" "$expected_samples"; then
    parsed="$(sample_count_for_file "$outfile" || true)"
    printf '%s\tfailed\tparsed_samples=%s expected=%s\n' "$name" "${parsed:-unknown}" "$expected_samples" >> "$FAILURES_FILE"
    rm -f "$outfile"
    continue
  fi
done

if grep -q $'\tfailed\t' "$FAILURES_FILE"; then
  failure_count="$(grep -c $'\tfailed\t' "$FAILURES_FILE")"
else
  failure_count=0
fi
echo "failure_count=$failure_count"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
exit "$failure_count"
