#!/usr/bin/env bash
# Fetch eight pinned PSRFITS SEARCH-mode SUBINT rows (plus their FITS header
# ranges) from public CSIRO DAP collections for Parkes project P1018.
#
# Every run refreshes the anonymous presigned S3 links (48 h expiry) from the
# DAP API, re-validates collection licence/access, and matches each file's
# exact DAP id, filename and fileSize before any byte-range request. Rows are
# fetched as exact HTTP 206 byte ranges, resumably, never the 12.27 GB files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="csiro_parkes_uwl_search_mode_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
HELPER="$RECIPE_DIR/scripts/parkes_psrfits.py"
API="https://data.csiro.au/dap/ws/v2"
UA="openzl-public-datasets-parkes-uwl/1.0"
HEADER_BYTES=25920
ROW_BYTES=54792232
MAX_ATTEMPTS="${MAX_ATTEMPTS:-12}"

mkdir -p "$DOWNLOAD_DIR/api" "$DOWNLOAD_DIR/headers" "$DOWNLOAD_DIR/rows" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

fetch_json() {
  local url="$1" out="$2"
  rm -f "$out.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors \
    --connect-timeout 60 --max-time 300 --max-filesize 20000000 \
    --user-agent "$UA" --header "Accept: application/json" \
    --output "$out.part" "$url"
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$out.part" \
    || { echo "FATAL: invalid JSON from $url" >&2; exit 1; }
  mv "$out.part" "$out"
}

# fetch_range URL START LENGTH TOTAL OUT
# Resumable exact byte-range download: each attempt requests only the missing
# tail, checks that the reply is HTTP 206 with the exact Content-Range, and
# appends whatever valid bytes arrived. Stalls are detected by speed limits,
# never by a hard --max-time.
fetch_range() {
  local url="$1" start="$2" length="$3" total="$4" out="$5"
  local part="$out.part" chunk="$out.chunk" hdr="$out.chunk.headers"
  local end=$((start + length - 1)) attempt=0 have from rc check
  touch "$part"
  while :; do
    have="$(stat -c %s "$part")"
    if [ "$have" -eq "$length" ]; then
      break
    fi
    if [ "$have" -gt "$length" ]; then
      echo "FATAL: partial $part larger than requested range" >&2
      rm -f "$part"
      return 1
    fi
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: $out still incomplete after $MAX_ATTEMPTS attempts ($have/$length bytes)" >&2
      return 1
    fi
    from=$((start + have))
    rm -f "$chunk" "$hdr"
    echo "range attempt=$attempt bytes=$from-$end have=$have/$length -> $(basename "$out")"
    set +e
    curl --fail --silent --show-error --location \
      --connect-timeout 60 --speed-limit 1024 --speed-time 120 \
      --max-filesize "$((length - have + 65536))" \
      --range "$from-$end" --user-agent "$UA" \
      --dump-header "$hdr" --output "$chunk" "$url"
    rc=$?
    python3 "$HELPER" check-range --headers "$hdr" --start "$from" --end "$end" --total "$total"
    check=$?
    set -e
    if [ "$check" -eq 0 ] && [ -f "$chunk" ]; then
      cat "$chunk" >> "$part"
    elif [ "$check" -eq 3 ]; then
      echo "FATAL: presigned link refused (HTTP 401/403/404/410); rerun to refresh links" >&2
      rm -f "$chunk" "$hdr"
      return 1
    else
      echo "discarding invalid range reply (curl rc=$rc)"
    fi
    rm -f "$chunk" "$hdr"
    if [ "$rc" -ne 0 ]; then
      sleep $((attempt * 10 < 60 ? attempt * 10 : 60))
    fi
  done
  mv "$part" "$out"
}

declare -A CHECKED_COLLECTION=()
while IFS=$'\t' read -r obs cid doi fid fname fsize fmd5 date_obs row hdr_sha aux_sha row_sha; do
  [ "$obs" = "observation_id" ] && continue
  [ -n "$obs" ] || continue
  base="$(basename "$fname")"
  echo "--- $obs collection=$cid file=$fname row=$row"

  meta="$DOWNLOAD_DIR/api/collection_$cid.json"
  listing="$DOWNLOAD_DIR/api/collection_${cid}_data.json"
  if [ -z "${CHECKED_COLLECTION[$cid]:-}" ]; then
    fetch_json "$API/collections/$cid" "$meta"
    python3 "$HELPER" check-collection --meta "$meta" --collection-id "$cid" --doi "$doi"
    fetch_json "$API/collections/$cid/data" "$listing"
    CHECKED_COLLECTION[$cid]=1
  fi
  url="$(python3 "$HELPER" resolve-url --data-json "$listing" --filename "$fname" --file-id "$fid" --file-size "$fsize")"

  header_out="$DOWNLOAD_DIR/headers/$base.header"
  if [ -s "$header_out" ] && printf '%s  %s\n' "$hdr_sha" "$header_out" | sha256sum --check --status; then
    echo "cache_hit header=$base"
  else
    rm -f "$header_out"
    fetch_range "$url" 0 "$HEADER_BYTES" "$fsize" "$header_out"
  fi
  python3 "$HELPER" check-header --header "$header_out" --sha256 "$hdr_sha" \
    --file-size "$fsize" --date-obs "$date_obs" --label "$base"

  row_start=$((HEADER_BYTES + row * ROW_BYTES))
  row_out="$DOWNLOAD_DIR/rows/$base.subint$(printf '%04d' "$row").row"
  if [ -s "$row_out" ] && [ "$(stat -c %s "$row_out")" -eq "$ROW_BYTES" ]; then
    echo "cache_hit row=$(basename "$row_out")"
  else
    rm -f "$row_out"
    fetch_range "$url" "$row_start" "$ROW_BYTES" "$fsize" "$row_out"
  fi
  if ! python3 "$HELPER" check-row --header "$header_out" --row "$row_out" --row-index "$row" \
      --file-size "$fsize" --date-obs "$date_obs" --aux-sha256 "$aux_sha" \
      --row-sha256 "${row_sha:-}" --label "$base"; then
    echo "FATAL: row validation failed; removing $row_out so a rerun refetches it" >&2
    rm -f "$row_out" "$row_out.sha256"
    exit 1
  fi
done < "$SOURCES"

echo "row checksums:"
cat "$DOWNLOAD_DIR"/rows/*.sha256
du -sb "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
