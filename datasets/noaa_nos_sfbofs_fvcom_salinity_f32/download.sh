#!/usr/bin/env bash
# Range-fetch the SFBOFS (FVCOM) nowcast salinity field from 52 pinned weekly
# sfbofs.t03z.YYYYMMDD.fields.n003.nc objects in the NOAA NODD bucket
# noaa-nos-ofs-pds. The 56.6 MB files are never downloaded whole: per file
# only the 256 KiB metadata head, two 4 KiB chunk-B-tree windows, the x/y node
# coordinates, the four raw salinity chunks and the time chunk (about 5.04 MB)
# are fetched. Every response must be HTTP 206 with the exact Content-Range,
# Content-Length and the pinned ETag (requests also carry If-Match), and each
# file must pass full semantic validation before the next one starts.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="noaa_nos_sfbofs_fvcom_salinity_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://noaa-nos-ofs-pds.s3.amazonaws.com"
HEAD_BYTES=262144
EXPECTED_FILES=52
UA="openzl-public-datasets-sfbofs-salinity/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

py() { python3 "$RECIPE_DIR/scripts/sfbofs_salinity.py" "$@"; }

py check-sources --sources "$RECIPE_DIR/sources.tsv"

# fetch_range URL START LENGTH DEST TOTAL ETAG
# Ranges are at most ~1.1 MB, so a failed attempt simply refetches the range.
fetch_range() {
  local url="$1" start="$2" length="$3" dest="$4" total="$5" etag="$6"
  local end=$((start + length - 1))
  local part="$dest.part" hdr="$dest.headers" attempt rc got
  if [[ -f "$dest" ]] && [[ "$(stat -c %s "$dest")" = "$length" ]]; then
    return 0
  fi
  rm -f "$dest"
  for attempt in 1 2 3 4 5 6; do
    rm -f "$part" "$hdr"
    rc=0
    curl --fail --silent --show-error --location --globoff \
      --retry 5 --retry-delay 5 --retry-all-errors \
      --connect-timeout 60 --speed-limit 1024 --speed-time 120 --max-time 900 \
      --max-filesize $((length + 4096)) \
      --header "If-Match: \"$etag\"" --range "$start-$end" --user-agent "$UA" \
      --dump-header "$hdr" --output "$part" "$url" || rc=$?
    got=0
    [[ -f "$part" ]] && got="$(stat -c %s "$part")"
    if (( rc == 0 && got == length )) \
      && py check-response --headers "$hdr" --start "$start" --end "$end" --total "$total" --etag "$etag"; then
      mv "$part" "$dest"
      rm -f "$hdr"
      return 0
    fi
    echo "attempt=$attempt rc=$rc bytes=$got range=$start-$end discarded" >&2
    sleep $((attempt * 10))
  done
  echo "FATAL: range $start-$end of $url failed after retries" >&2
  exit 1
}

fetch_plan() {
  local url="$1" fdir="$2" total="$3" etag="$4" plan="$5"
  local name start length
  while IFS=$'\t' read -r name start length; do
    [[ -n "$name" ]] || continue
    fetch_range "$url" "$start" "$length" "$fdir/$name.bin" "$total" "$etag"
  done <<< "$plan"
}

SUMMARY="$DOWNLOAD_DIR/download_plan.tsv"
printf 'date\tsegment\tsource_byte_offset\tbytes\tsha256\n' > "$SUMMARY.part"
files=0
fetched_bytes=0
while IFS=$'\t' read -r date key size_bytes etag <&3; do
  [[ "$date" != "date" ]] || continue
  url="$BASE_URL/$key"
  fdir="$DOWNLOAD_DIR/$date"
  mkdir -p "$fdir"
  if [[ -f "$fdir/.validated" ]] && py check-file --dir "$fdir" --date "$date" > /dev/null; then
    echo "cache_hit date=$date"
  else
    rm -f "$fdir/.validated"
    echo "[$(date -Is)] date=$date key=$key etag=$etag"
    fetch_range "$url" 0 "$HEAD_BYTES" "$fdir/head.bin" "$size_bytes" "$etag"
    meta_plan="$(py plan-meta --dir "$fdir" --date "$date")"
    fetch_plan "$url" "$fdir" "$size_bytes" "$etag" "$meta_plan"
    data_plan="$(py plan-data --dir "$fdir" --date "$date")"
    fetch_plan "$url" "$fdir" "$size_bytes" "$etag" "$data_plan"
    if ! py check-file --dir "$fdir" --date "$date"; then
      rm -rf "$fdir.invalid"
      mv "$fdir" "$fdir.invalid"
      echo "FATAL: semantically invalid salinity field for $date (moved to $fdir.invalid)" >&2
      exit 1
    fi
    touch "$fdir/.validated"
  fi
  meta_plan="$(py plan-meta --dir "$fdir" --date "$date")"
  data_plan="$(py plan-data --dir "$fdir" --date "$date")"
  while IFS=$'\t' read -r name start length; do
    [[ -n "$name" ]] || continue
    printf '%s\t%s\t%s\t%s\t%s\n' "$date" "$name" "$start" "$length" \
      "$(sha256sum "$fdir/$name.bin" | awk '{print $1}')" >> "$SUMMARY.part"
    fetched_bytes=$((fetched_bytes + length))
  done <<< "$(printf 'head\t0\t%s\n%s\n%s\n' "$HEAD_BYTES" "$meta_plan" "$data_plan")"
  files=$((files + 1))
done 3< "$RECIPE_DIR/sources.tsv"
mv "$SUMMARY.part" "$SUMMARY"

if [[ "$files" != "$EXPECTED_FILES" ]]; then
  echo "FATAL: validated $files files, expected $EXPECTED_FILES" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$files fetched_bytes=$fetched_bytes"
