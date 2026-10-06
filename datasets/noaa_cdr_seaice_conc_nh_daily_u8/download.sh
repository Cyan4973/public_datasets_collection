#!/usr/bin/env bash
# Download the NOAA/NSIDC sea-ice concentration CDR (G02202 v4, v04r00)
# Northern-Hemisphere daily NetCDF4 files for 2022-2024 (all F17) from the
# public NOAA Open Data Dissemination S3 bucket, plus the per-file .mnf
# checksum manifests.  Anonymous HTTPS only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="noaa_cdr_seaice_conc_nh_daily_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LISTING_DIR="$DOWNLOAD_DIR/listings"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://noaa-cdr-sea-ice-concentration-pds.s3.amazonaws.com"
YEARS="2022 2023 2024"
MAX_PASSES=6
UA="openzl-public-datasets-noaa-cdr-seaice/1.0"
PY="$RECIPE_DIR/scripts/seaice_conc.py"

mkdir -p "$DOWNLOAD_DIR" "$LISTING_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$LISTING_DIR"/*.xml "$DOWNLOAD_DIR/inventory.tsv"
fi

# 1. Small S3 ListObjectsV2 pages (one per year and prefix; each < 1000 keys).
fetch_listing() {
  local name="$1" prefix="$2" out="$LISTING_DIR/$1.xml"
  if [ -s "$out" ]; then
    echo "cache_hit listing=$name"
    return
  fi
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors --max-time 300 \
    --user-agent "$UA" --output "$out.part" \
    "$BASE_URL/?list-type=2&prefix=$prefix"
  mv "$out.part" "$out"
  echo "fetched listing=$name bytes=$(wc -c < "$out" | tr -d ' ')"
}
for year in $YEARS; do
  fetch_listing "daily_$year" "data/final/north/daily/$year/"
  fetch_listing "checksums_$year" "data/final/north/checksums/daily/$year/"
done

# 2. Pin the exact file set: 1096 f17 v04r00 daily files, sizes, MD5 ETags.
python3 "$PY" inventory --listings "$LISTING_DIR" --out "$DOWNLOAD_DIR/inventory.tsv"

# 3./4. Fetch .mnf manifests, then the NetCDF files; validate between passes.
run_passes() {
  local kind="$1" pass config pending
  config="$DOWNLOAD_DIR/curl_$kind.cfg"
  for pass in $(seq 1 "$MAX_PASSES"); do
    python3 "$PY" plan --kind "$kind" --inventory "$DOWNLOAD_DIR/inventory.tsv" \
      --downloads "$DOWNLOAD_DIR" --base-url "$BASE_URL" --config "$config"
    pending="$(grep -c '^url = ' "$config" || true)"
    if [ "$pending" = "0" ]; then
      echo "kind=$kind complete after pass=$pass"
      rm -f "$config"
      return 0
    fi
    echo "[$(date -Is)] kind=$kind pass=$pass fetching=$pending"
    curl --fail --silent --show-error --location \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
      --continue-at - --parallel --parallel-max 8 \
      --user-agent "$UA" --config "$config" || echo "curl reported failures on pass=$pass; revalidating"
  done
  python3 "$PY" plan --kind "$kind" --inventory "$DOWNLOAD_DIR/inventory.tsv" \
    --downloads "$DOWNLOAD_DIR" --base-url "$BASE_URL" --config "$config"
  if [ "$(grep -c '^url = ' "$config" || true)" != "0" ]; then
    echo "FATAL: kind=$kind still incomplete after $MAX_PASSES passes" >&2
    exit 1
  fi
  rm -f "$config"
}
run_passes mnf
run_passes nc

# 5. Semantic check: every file decodes to a valid cdr_seaice_conc grid.
python3 "$PY" check-downloads --downloads "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
