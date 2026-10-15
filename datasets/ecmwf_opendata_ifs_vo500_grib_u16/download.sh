#!/usr/bin/env bash
# Fetch the 500 hPa relative-vorticity (vo) 24 h forecast GRIB2 message of every
# 00z IFS HRES run in the ECMWF open-data 0p4-beta stream, 2023-01-18..2023-06-27,
# from the public AWS Open Data bucket s3://ecmwf-forecasts (eu-central-1).
#
# Per day: GET the small JSON-lines .index of the 24 h file, pick the single
# param=vo / levelist=500 line (must have _length 811996), then range-GET exactly
# that message. Days whose .index is absent (HTTP 404) are skipped and logged;
# S3 "SlowDown" 503s are retried with back-off; any day still failing with a
# transient error makes the script exit non-zero so a re-run resumes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ecmwf_opendata_ifs_vo500_grib_u16"
DL="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PARSER="$RECIPE_DIR/scripts/grib2_vo500.py"
# Canonical S3 endpoint and the CloudFront distribution listed for this bucket in the AWS
# Open Data Registry entry (same objects; CloudFront cache hits avoid S3 SlowDown throttling).
BASE="https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
CDN="https://d2zvc0wgha4k2l.cloudfront.net"
START="2023-01-18"   # first day present in the bucket
END="2023-06-27"     # last 00z run before IFS 48r1 (06 UTC 2023-06-27) switched open data to CCSDS (template 5.42)
MSG_LEN=811996
MIN_DAYS=150         # of 161 calendar days; fewer present days is treated as a broken pull
UA="openzl-public-datasets-ecmwf-opendata-download/1.0"

mkdir -p "$DL/index" "$DL/grib" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID window=$START..$END"

# fetch_range KEY OUT FIRST LAST -> 0 ok, 4 not found (404), 3 persistent transient failure.
# Range GET of bytes FIRST..LAST into OUT. Truncated transfers (curl exit 18, seen on both
# hosts) are resumed: the next attempt requests only the missing tail and appends it.
# Each piece must be answered 206 with a matching Content-Range start; attempts alternate
# CloudFront (odd) and the S3 endpoint (even).
fetch_range() {
  local key="$1" out="$2" first="$3" last="$4" attempt code delay url have start crc hdr cr
  local want=$(( last - first + 1 ))
  rm -f "$out.part"; : > "$out.part"
  for attempt in $(seq 1 20); do
    have="$(stat -c %s "$out.part")"
    if (( have == want )); then mv "$out.part" "$out"; return 0; fi
    if (( have > want )); then : > "$out.part"; have=0; fi
    start=$(( first + have ))
    if (( attempt % 2 )); then url="$CDN/$key"; else url="$BASE/$key"; fi
    hdr="$out.hdr"
    crc=0
    code="$(curl --globoff --silent --show-error --location --range "$start-$last" \
      --max-filesize 1000000 --max-time 300 --speed-limit 1024 --speed-time 60 --user-agent "$UA" \
      --dump-header "$hdr" --output "$out.piece" --write-out '%{http_code}' "$url")" || crc=$?
    cr="$(tr -d '\r' < "$hdr" 2>/dev/null | awk 'tolower($1)=="content-range:"{print $3}' | tail -n 1)"
    rm -f "$hdr"
    if [[ "$code" == 206 && "$cr" == "$start-"* && -s "$out.piece" && "$(head -c 5 "$out.piece")" != "<?xml" ]]; then
      cat "$out.piece" >> "$out.part"
      rm -f "$out.piece"
      have="$(stat -c %s "$out.part")"
      if (( have == want )); then mv "$out.part" "$out"; return 0; fi
      echo "  partial attempt=$attempt curl_rc=$crc have=$have/$want url=$url"
      sleep 2
      continue
    fi
    rm -f "$out.piece"
    if [[ "$code" == 404 ]]; then rm -f "$out.part"; return 4; fi
    delay=$(( attempt * 5 )); (( delay > 60 )) && delay=60
    echo "  retry attempt=$attempt http=$code curl_rc=$crc content_range=${cr:-none} sleep=${delay}s url=$url"
    sleep "$delay"
  done
  rm -f "$out.part"
  return 3
}

# fetch KEY OUT -> 0 ok, 4 not found (404), 3 persistent transient failure (small whole objects).
# Attempts alternate CloudFront (odd) and the S3 endpoint (even).
fetch() {
  local key="$1" out="$2" attempt code delay url crc
  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
    rm -f "$out.part"
    if (( attempt % 2 )); then url="$CDN/$key"; else url="$BASE/$key"; fi
    crc=0
    code="$(curl --globoff --silent --show-error --location \
      --max-filesize 200000 --max-time 120 --speed-limit 1024 --speed-time 60 --user-agent "$UA" \
      --output "$out.part" --write-out '%{http_code}' "$url")" || crc=$?
    # Accept only a complete transfer (curl exit 0) answered 200.
    if [[ "$code" == 200 && $crc -eq 0 ]]; then
      mv "$out.part" "$out"; return 0
    fi
    if [[ "$code" == 404 ]]; then rm -f "$out.part"; return 4; fi
    delay=$(( attempt * 5 )); (( delay > 60 )) && delay=60
    echo "  retry attempt=$attempt http=$code curl_rc=$crc sleep=${delay}s url=$url"
    sleep "$delay"
  done
  rm -f "$out.part"
  return 3
}

MISSING="$DL/missing_days.tsv"
printf 'run_date\treason\n' > "$MISSING"
transient=0
present=0
d="$START"
while [[ "$(date -d "$d" +%Y%m%d)" -le "$(date -d "$END" +%Y%m%d)" ]]; do
  ymd="$(date -d "$d" +%Y%m%d)"
  d="$(date -d "$d + 1 day" +%Y-%m-%d)"
  stem="$ymd/00z/0p4-beta/oper/${ymd}000000-24h-oper-fc"
  idx="$DL/index/$ymd.index"
  grib="$DL/grib/$ymd.grib2"

  if [[ -s "$grib" && -s "$idx" ]] && python3 -I "$PARSER" check "$grib" "$ymd" >/dev/null 2>&1; then
    echo "cache_hit $ymd"
    present=$((present + 1))
    continue
  fi

  if [[ ! -s "$idx" ]] || ! python3 -I "$PARSER" pick-index "$idx" "$ymd" >/dev/null 2>&1; then
    rc=0; fetch "$stem.index" "$idx" || rc=$?
    if [[ $rc -eq 4 ]]; then
      echo "missing $ymd index HTTP 404"; printf '%s\tindex_http_404\n' "$ymd" >> "$MISSING"; continue
    elif [[ $rc -ne 0 ]]; then
      echo "TRANSIENT $ymd index fetch failed after retries"; transient=$((transient + 1)); continue
    fi
    sleep 1
  fi
  # Semantic validation of the index (JSON lines, exactly one vo/500/24h line, _length 811996).
  # A failing index (e.g. an error body) is discarded and the run fails so a re-run retries it.
  if ! python3 -I "$PARSER" pick-index "$idx" "$ymd" > "$idx.pick"; then
    echo "INVALID $ymd index: $(head -c 120 "$idx" | tr -c '[:print:]' '.')"
    rm -f "$idx" "$idx.pick"; transient=$((transient + 1)); continue
  fi
  read -r offset length < "$idx.pick"; rm -f "$idx.pick"
  [[ "$length" = "$MSG_LEN" ]] || { echo "unexpected length $length for $ymd" >&2; exit 1; }
  last=$((offset + length - 1))

  rc=0; fetch_range "$stem.grib2" "$grib" "$offset" "$last" || rc=$?
  if [[ $rc -eq 4 ]]; then
    echo "missing $ymd grib2 HTTP 404"; printf '%s\tgrib2_http_404\n' "$ymd" >> "$MISSING"; rm -f "$idx"; continue
  elif [[ $rc -ne 0 ]]; then
    echo "TRANSIENT $ymd grib2 fetch failed after retries"; transient=$((transient + 1)); continue
  fi
  size="$(stat -c %s "$grib")"
  if [[ "$size" != "$MSG_LEN" || "$(head -c 4 "$grib")" != "GRIB" ]]; then
    # An S3 error body (e.g. SlowDown XML) or a short read: discard and fail this run.
    echo "INVALID $ymd body size=$size head=$(head -c 16 "$grib" | tr -c '[:print:]' '.')"
    rm -f "$grib"; transient=$((transient + 1)); continue
  fi
  # Full GRIB2 structural check (template 5.0, 16 bits, 405900 points, bitmap 255, vo/500/24h, date).
  python3 -I "$PARSER" check "$grib" "$ymd" || { echo "semantic check failed for $ymd" >&2; rm -f "$grib"; exit 1; }
  present=$((present + 1))
  sleep 1
done

if [[ $transient -gt 0 ]]; then
  echo "[$(date -Is)] $transient day(s) failed transiently; re-run download.sh to resume" >&2
  exit 1
fi
[[ $present -ge $MIN_DAYS ]] || { echo "only $present days present (< $MIN_DAYS)" >&2; exit 1; }

# Record the realized message set with checksums (build.sh re-checks these).
PLAN="$DL/messages.tsv"
printf 'run_date\toffset\tlength\tsha256\turl\n' > "$PLAN.tmp"
for grib in "$DL"/grib/*.grib2; do
  ymd="$(basename "$grib" .grib2)"
  read -r offset length < <(python3 -I "$PARSER" pick-index "$DL/index/$ymd.index" "$ymd")
  sha="$(sha256sum "$grib" | awk '{print $1}')"
  printf '%s\t%s\t%s\t%s\t%s\n' "$ymd" "$offset" "$length" "$sha" \
    "$BASE/$ymd/00z/0p4-beta/oper/${ymd}000000-24h-oper-fc.grib2" >> "$PLAN.tmp"
done
mv "$PLAN.tmp" "$PLAN"
missing_n=$(( $(wc -l < "$MISSING") - 1 ))
total_bytes="$(du -sb "$DL" | awk '{print $1}')"
echo "[$(date -Is)] download done dataset=$DATASET_ID days_present=$present days_missing=$missing_n bytes_on_disk=$total_bytes"
