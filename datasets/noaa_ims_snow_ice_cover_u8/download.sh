#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_ims_snow_ice_cover_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
GRID_DIR="$DOWNLOAD_DIR/grids"
mkdir -p "$LOG_DIR" "$GRID_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

BASE_URL="${IMS_BASE_URL:-https://noaadata.apps.nsidc.org/NOAA/G02156/4km/2024}"
MAX_COMPRESSED_BYTES="${IMS_MAX_COMPRESSED_BYTES:-100000000}"
MIN_UNCOMPRESSED_BYTES="${IMS_MIN_UNCOMPRESSED_BYTES:-37748736}"
UA="${IMS_UA:-openzl-public-datasets/1.0}"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

cat > "$PLAN" <<'EOF'
date_utc	doy	filename
2024-01-01	001	ims2024001_00UTC_4km_v1.3.asc.gz
2024-02-01	032	ims2024032_00UTC_4km_v1.3.asc.gz
2024-03-01	061	ims2024061_00UTC_4km_v1.3.asc.gz
2024-04-01	092	ims2024092_00UTC_4km_v1.3.asc.gz
2024-05-01	122	ims2024122_00UTC_4km_v1.3.asc.gz
2024-06-01	153	ims2024153_00UTC_4km_v1.3.asc.gz
2024-07-01	183	ims2024183_00UTC_4km_v1.3.asc.gz
2024-08-01	214	ims2024214_00UTC_4km_v1.3.asc.gz
2024-09-01	245	ims2024245_00UTC_4km_v1.3.asc.gz
2024-10-01	275	ims2024275_00UTC_4km_v1.3.asc.gz
2024-11-01	306	ims2024306_00UTC_4km_v1.3.asc.gz
2024-12-01	336	ims2024336_00UTC_4km_v1.3.asc.gz
EOF

while IFS=$'\t' read -r date_utc doy filename; do
  [ "$date_utc" != "date_utc" ] || continue
  url="${BASE_URL%/}/$filename"
  out="$GRID_DIR/$filename"
  if [ -f "$out" ] && gzip -t "$out" 2>/dev/null && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    echo "cache_hit date=$date_utc file=$filename bytes=$(wc -c < "$out" | tr -d ' ')"
  else
    echo "fetch date=$date_utc doy=$doy url=$url"
    rm -f "$out.part"
    curl --globoff -fL --retry 5 --retry-all-errors --retry-delay 5 \
      --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
      -A "$UA" -o "$out.part" "$url"
    gzip -t "$out.part"
    mv "$out.part" "$out"
  fi

  compressed_bytes="$(wc -c < "$out" | tr -d ' ')"
  if [ "$compressed_bytes" -le 0 ] || [ "$compressed_bytes" -gt "$MAX_COMPRESSED_BYTES" ]; then
    echo "FATAL: implausible compressed size file=$filename bytes=$compressed_bytes max=$MAX_COMPRESSED_BYTES" >&2
    exit 1
  fi

  uncompressed_bytes="$(gzip -cd "$out" | wc -c | tr -d ' ')"
  if [ "$uncompressed_bytes" -lt "$MIN_UNCOMPRESSED_BYTES" ]; then
    echo "FATAL: decompressed payload too small file=$filename bytes=$uncompressed_bytes min=$MIN_UNCOMPRESSED_BYTES" >&2
    exit 1
  fi
  echo "validated date=$date_utc compressed_bytes=$compressed_bytes uncompressed_bytes=$uncompressed_bytes"
done < "$PLAN"

echo "[$(date -Is)] download done dataset=$DATASET_ID files=12"
