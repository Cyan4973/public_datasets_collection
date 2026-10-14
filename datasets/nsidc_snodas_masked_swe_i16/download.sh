#!/usr/bin/env bash
# Fetch only the SNODAS SWE (product 1034) .dat.gz/.txt.gz members of 20 pinned
# daily masked-CONUS tars via HTTP range GETs; never downloads whole tars.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nsidc_snodas_masked_swe_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
MEMBER_DIR="$DOWNLOAD_DIR/members"
mkdir -p "$LOG_DIR" "$MEMBER_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

PLAN="$RECIPE_DIR/plan.tsv"
CHECK="$RECIPE_DIR/scripts/check_member.py"
UA="${SNODAS_UA:-openzl-public-datasets/1.0}"
# Optional mirror override; must preserve the /YYYY/MM_Mon/SNODAS_YYYYMMDD.tar layout.
BASE_OVERRIDE="${SNODAS_BASE_URL:-}"
PINNED_BASE="https://noaadata.apps.nsidc.org/NOAA/G02158/masked"
CHECKSUMS="$DOWNLOAD_DIR/member_checksums.tsv"

fetch_range() {  # url start length out
  local url="$1" start="$2" length="$3" out="$4"
  local end=$((start + length - 1))
  rm -f "$out.part"
  curl --globoff -fsSL --retry 10 --retry-all-errors --retry-delay 5 \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
    -A "$UA" -r "$start-$end" -o "$out.part" "$url"
  local got
  got="$(wc -c < "$out.part" | tr -d ' ')"
  if [ "$got" != "$length" ]; then
    echo "FATAL: range read returned $got bytes, expected $length (server ignored Range?) url=$url start=$start" >&2
    exit 1
  fi
  mv "$out.part" "$out"
}

printf 'date\tmember\tsize_bytes\tmd5\tsha256\n' > "$CHECKSUMS.tmp"
n=0
while IFS=$'\t' read -r date tar_url dat_member dat_offset dat_size dat_crc32 dat_isize txt_member txt_offset txt_size; do
  [ "$date" != "date" ] || continue
  if [ -n "$BASE_OVERRIDE" ]; then
    tar_url="${BASE_OVERRIDE%/}${tar_url#"$PINNED_BASE"}"
  fi
  n=$((n + 1))
  dat_out="$MEMBER_DIR/$dat_member"
  txt_out="$MEMBER_DIR/$txt_member"

  # Header member (.txt.gz): small; always re-validate header block + content.
  if [ -f "$txt_out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && python3 -I "$CHECK" txt "$txt_out" "$date" 2>/dev/null; then
    echo "cache_hit date=$date member=$txt_member"
  else
    fetch_range "$tar_url" $((txt_offset - 512)) 512 "$MEMBER_DIR/.hdr_txt_$date"
    python3 -I "$CHECK" header "$MEMBER_DIR/.hdr_txt_$date" "$txt_member" "$txt_size"
    fetch_range "$tar_url" "$txt_offset" "$txt_size" "$txt_out"
    python3 -I "$CHECK" txt "$txt_out" "$date"
    rm -f "$MEMBER_DIR/.hdr_txt_$date"
    echo "fetched date=$date member=$txt_member bytes=$txt_size"
  fi

  # Raster member (.dat.gz): check the ustar header first, then the pinned
  # gzip trailer CRC32/ISIZE and full decompression.
  if [ -f "$dat_out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && [ "$(wc -c < "$dat_out" | tr -d ' ')" = "$dat_size" ]; then
    echo "cache_hit date=$date member=$dat_member"
  else
    fetch_range "$tar_url" $((dat_offset - 512)) 512 "$MEMBER_DIR/.hdr_dat_$date"
    python3 -I "$CHECK" header "$MEMBER_DIR/.hdr_dat_$date" "$dat_member" "$dat_size"
    rm -f "$MEMBER_DIR/.hdr_dat_$date"
    echo "fetch date=$date member=$dat_member offset=$dat_offset bytes=$dat_size"
    fetch_range "$tar_url" "$dat_offset" "$dat_size" "$dat_out"
  fi
  sums="$(python3 -I "$CHECK" dat "$dat_out" "$dat_crc32" "$dat_isize")" || { rm -f "$dat_out"; echo "FATAL: invalid raster member $dat_member (removed)" >&2; exit 1; }
  md5="$(echo "$sums" | sed -n 's/.*md5=\([0-9a-f]*\).*/\1/p')"
  sha="$(echo "$sums" | sed -n 's/.*sha256=\([0-9a-f]*\).*/\1/p')"
  printf '%s\t%s\t%s\t%s\t%s\n' "$date" "$dat_member" "$dat_size" "$md5" "$sha" >> "$CHECKSUMS.tmp"
  echo "validated date=$date crc32=$dat_crc32 isize=$dat_isize md5=$md5"
done < "$PLAN"

if [ "$n" -ne 20 ]; then
  echo "FATAL: expected 20 plan rows, processed $n" >&2
  exit 1
fi
mv "$CHECKSUMS.tmp" "$CHECKSUMS"
echo "[$(date -Is)] download done dataset=$DATASET_ID dates=$n bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
