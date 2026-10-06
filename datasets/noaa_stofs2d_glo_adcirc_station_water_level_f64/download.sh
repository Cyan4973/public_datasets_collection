#!/usr/bin/env bash
# Download the 40 pinned STOFS-2D-Global v2.1 00z fort.61 station files
# (stofs_2d_glo.YYYYMMDD/00/rerun/stofs_2d_glo_fcst.61.nc, every 20 days from
# 2024-06-01 to 2026-07-21) from the public NOAA NODD bucket noaa-gestofs-pds.
# Anonymous HTTPS only.  Every object is first checked against a fresh S3
# listing (key, size, ETag pinned in sources.tsv), then fetched resumably and
# accepted only if its size and locally recomputed multipart ETag match and it
# decodes to the expected v2.1 zeta matrix.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="noaa_stofs2d_glo_adcirc_station_water_level_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LISTING_DIR="$DOWNLOAD_DIR/listings"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://noaa-gestofs-pds.s3.amazonaws.com"
SOURCES="$RECIPE_DIR/sources.tsv"
PY="$RECIPE_DIR/scripts/stofs61.py"
MAX_PASSES=6
UA="openzl-public-datasets-noaa-stofs2d/1.0"

mkdir -p "$DOWNLOAD_DIR/nc" "$LISTING_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

export PYTHONDONTWRITEBYTECODE=1
if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -f "$LISTING_DIR"/*.xml
fi

# 1. One small ListObjectsV2 request per pinned object (prefix = exact key).
tail -n +2 "$SOURCES" | while IFS=$'\t' read -r day key _size _etag; do
  out="$LISTING_DIR/${day//-/}.xml"
  if [ -s "$out" ]; then
    continue
  fi
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors --max-time 120 \
    --user-agent "$UA" --output "$out.part" \
    "$BASE_URL/?list-type=2&prefix=$key"
  mv "$out.part" "$out"
done
python3 "$PY" check-listings --sources "$SOURCES" --downloads "$DOWNLOAD_DIR"

# 2. Liveness: one-byte range GET of the first pinned object.
first_key="$(sed -n '2p' "$SOURCES" | cut -f2)"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$BASE_URL/$first_key"
echo "liveness=ok"

# 3. Resumable fetch passes; stofs61.py plan validates and promotes .part files
#    (size + multipart ETag) between passes and lists what is still missing.
config="$DOWNLOAD_DIR/curl_nc.cfg"
done_ok=0
for pass in $(seq 1 "$MAX_PASSES"); do
  python3 "$PY" plan --sources "$SOURCES" --downloads "$DOWNLOAD_DIR" --base-url "$BASE_URL" --config "$config"
  pending="$(grep -c '^url = ' "$config" || true)"
  if [ "$pending" = "0" ]; then
    echo "all objects present after pass=$pass"
    done_ok=1
    break
  fi
  echo "[$(date -Is)] pass=$pass fetching=$pending"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
    --continue-at - --parallel --parallel-max 4 \
    --user-agent "$UA" --config "$config" || echo "curl reported failures on pass=$pass; revalidating"
done
if [ "$done_ok" != "1" ]; then
  python3 "$PY" plan --sources "$SOURCES" --downloads "$DOWNLOAD_DIR" --base-url "$BASE_URL" --config "$config"
  if [ "$(grep -c '^url = ' "$config" || true)" != "0" ]; then
    echo "FATAL: downloads still incomplete after $MAX_PASSES passes" >&2
    exit 1
  fi
fi
rm -f "$config"

# 4. Semantic check: every file is the pinned v2.1 product and decodes cleanly.
python3 "$PY" check-downloads --sources "$SOURCES" --downloads "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
