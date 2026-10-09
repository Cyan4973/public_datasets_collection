#!/usr/bin/env bash
# Download the 159 pinned USCRN subhourly01 2024 station-year files plus the
# product HEADERS.txt / readme.txt, validating every payload semantically.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_uscrn_subhourly_relative_humidity_u8"
BASE_URL="https://www.ncei.noaa.gov/pub/data/uscrn/products/subhourly01"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
SOURCE_DIR="$DOWNLOAD_DIR/2024"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-uscrn-download/1.0"
EXPECTED_FILES=159
EXPECTED_BYTES=2252441520
LINE_BYTES=135

mkdir -p "$SOURCE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch() {
  # fetch <url> <target>: resumable, stall-bounded (no hard max-time).
  local url="$1" target="$2"
  curl --globoff --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 120 \
    --continue-at - --user-agent "$UA" --output "$target.part" "$url"
  mv "$target.part" "$target"
}

# Product documentation: the column layout is validated against HEADERS.txt.
for doc in HEADERS.txt readme.txt; do
  rm -f "$DOWNLOAD_DIR/$doc.part"
  curl --globoff --fail --silent --show-error --location --retry 5 --retry-delay 5 \
    --retry-all-errors --max-time 120 --user-agent "$UA" \
    --output "$DOWNLOAD_DIR/$doc.part" "$BASE_URL/$doc"
  mv "$DOWNLOAD_DIR/$doc.part" "$DOWNLOAD_DIR/$doc"
done
header_line="$(sed -n 2p "$DOWNLOAD_DIR/HEADERS.txt" | tr -s ' ' | sed 's/ *$//')"
expected_header="WBANNO UTC_DATE UTC_TIME LST_DATE LST_TIME CRX_VN LONGITUDE LATITUDE AIR_TEMPERATURE PRECIPITATION SOLAR_RADIATION SR_FLAG SURFACE_TEMPERATURE ST_TYPE ST_FLAG RELATIVE_HUMIDITY RH_FLAG SOIL_MOISTURE_5 SOIL_TEMPERATURE_5 WETNESS WET_FLAG WIND_1_5 WIND_FLAG"
[[ "$header_line" = "$expected_header" ]] || {
  echo "HEADERS.txt column layout changed: '$header_line'" >&2
  exit 1
}
grep -q "16   RELATIVE_HUMIDITY  \[5 chars\]  cols 95 -- 99" "$DOWNLOAD_DIR/readme.txt" || {
  echo "readme.txt no longer documents RELATIVE_HUMIDITY at cols 95-99" >&2
  exit 1
}
grep -q "17   RH_FLAG  \[1 chars\]  cols 101 -- 101" "$DOWNLOAD_DIR/readme.txt" || {
  echo "readme.txt no longer documents RH_FLAG at col 101" >&2
  exit 1
}
echo "documentation ok: 23-column subhourly01 layout, RH cols 95-99, RH_FLAG col 101"

PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'filename\tsize_bytes\tlisting_last_modified\tremote_last_modified\tsha256\tline_count\twbanno\n' > "$PLAN.tmp"

count=0
total=0
while IFS=$'\t' read -r -u 3 filename size_bytes listing_lm pinned_sha256; do
  [[ "$filename" != "filename" ]] || continue
  target="$SOURCE_DIR/$filename"
  url="$BASE_URL/2024/$filename"
  remote_lm="$(curl --globoff --fail --silent --show-error --location --head --max-time 60 \
      --retry 5 --retry-delay 5 --retry-all-errors --user-agent "$UA" "$url" \
    | tr -d '\r' | awk -F': ' 'tolower($1)=="last-modified"{v=$2} END{print v}')"
  if [[ -s "$target" && "$(stat -c %s "$target")" = "$size_bytes" ]]; then
    echo "cache_hit file=$filename bytes=$size_bytes"
  else
    rm -f "$target"
    if [[ -f "$target.part" && "$(stat -c %s "$target.part")" -gt "$size_bytes" ]]; then
      echo "discarding oversized partial file=$filename"
      rm -f "$target.part"
    fi
    if [[ -f "$target.part" && "$(stat -c %s "$target.part")" = "$size_bytes" ]]; then
      echo "completing finished partial file=$filename"
      mv "$target.part" "$target"
    else
      echo "fetch file=$filename bytes=$size_bytes remote_last_modified='$remote_lm'"
      fetch "$url" "$target"
    fi
  fi
  actual_size="$(stat -c %s "$target")"
  if [[ "$actual_size" != "$size_bytes" ]]; then
    echo "size mismatch file=$filename expected=$size_bytes actual=$actual_size" >&2
    rm -f "$target"
    exit 1
  fi
  # Semantic validation: fixed 135-byte lines, 23 whitespace fields, one WBANNO,
  # 2024 UTC dates (plus the 2025-01-01 00:00 closing interval), integer RH and
  # a single-digit RH flag.
  validation="$(awk -v L=$((LINE_BYTES - 1)) '
    length($0) != L { print "bad_length line=" NR; bad = 1; exit }
    NF != 23 { print "bad_field_count line=" NR " nf=" NF; bad = 1; exit }
    $1 !~ /^[0-9]+$/ { print "bad_wbanno line=" NR; bad = 1; exit }
    NR == 1 { w = $1 }
    $1 != w { print "mixed_wbanno line=" NR; bad = 1; exit }
    !($2 ~ /^2024[01][0-9][0-3][0-9]$/ || ($2 == "20250101" && $3 == "0000")) { print "bad_utc_date line=" NR " date=" $2; bad = 1; exit }
    $16 !~ /^-?[0-9]+$/ { print "bad_rh line=" NR " rh=" $16; bad = 1; exit }
    $17 !~ /^[0-9]$/ { print "bad_rh_flag line=" NR " flag=" $17; bad = 1; exit }
    END { if (!bad && NR > 0) print "ok " NR " " w }
  ' "$target")"
  read -r status lines wbanno <<<"$validation"
  if [[ "$status" != "ok" ]]; then
    echo "invalid payload file=$filename: $validation" >&2
    exit 1
  fi
  if [[ $((lines * LINE_BYTES)) -ne "$actual_size" ]]; then
    echo "line count mismatch file=$filename lines=$lines bytes=$actual_size" >&2
    exit 1
  fi
  sha256="$(sha256sum "$target" | awk '{print $1}')"
  if [[ -n "$pinned_sha256" && "$pinned_sha256" != "-" && "$sha256" != "$pinned_sha256" ]]; then
    echo "SHA-256 mismatch file=$filename expected=$pinned_sha256 actual=$sha256 (upstream revision?)" >&2
    exit 1
  fi
  if [[ -n "$remote_lm" ]]; then
    remote_day="$(date -u -d "$remote_lm" +%Y-%m-%d 2>/dev/null || echo "$remote_lm")"
    if [[ "$remote_day" != "${listing_lm%% *}" ]]; then
      echo "note: upstream Last-Modified differs from pinned listing file=$filename listing='$listing_lm' remote='$remote_lm'"
    fi
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$filename" "$size_bytes" "$listing_lm" \
    "$remote_lm" "$sha256" "$lines" "$wbanno" >> "$PLAN.tmp"
  count=$((count + 1))
  total=$((total + actual_size))
done 3< "$RECIPE_DIR/sources.tsv"
mv "$PLAN.tmp" "$PLAN"

[[ "$count" = "$EXPECTED_FILES" ]] || { echo "unexpected file count: $count" >&2; exit 1; }
[[ "$total" = "$EXPECTED_BYTES" ]] || { echo "unexpected total bytes: $total" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$total plan=$PLAN"
