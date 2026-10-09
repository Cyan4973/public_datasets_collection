#!/usr/bin/env bash
# Download the 196 pinned GOES-16 EXIS/XRS science-quality 1-s flux daily
# NetCDF4 files (xrsf-l2-flx1s_science, v2-2-1; the 1st and 15th of every
# month from 2017-02-15 to 2025-04-01) from NOAA NCEI's public HTTPS archive.
# Anonymous access only.  Files are fetched into .part files (resumable),
# promoted only at the pinned byte size (and pinned SHA-256 where listed in
# files.tsv), then fully decoded as a semantic check.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="noaa_goes16_xrs_1s_flux_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
INVENTORY="$RECIPE_DIR/files.tsv"
PY="$RECIPE_DIR/scripts/xrs_flux.py"
BASE_URL="https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/goes16/l2/data/xrsf-l2-flx1s_science"
UA="openzl-public-datasets-goes16-xrs/1.0"
MAX_PASSES=6

mkdir -p "$DOWNLOAD_DIR/daily" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Liveness: one-byte range GET of the first pinned file.
first="$(awk -F'\t' 'NR==2 {print $2}' "$INVENTORY")"
stamp="${first#*_d}"
probe="$(curl --fail --silent --show-error --location --max-time 60 --retry 3 \
  --user-agent "$UA" --range 0-0 "$BASE_URL/${stamp:0:4}/${stamp:4:2}/$first" | od -An -tx1 | tr -d ' \n')"
if [ "$probe" != "89" ]; then
  echo "FATAL: liveness probe did not return the HDF5 signature byte (got '$probe')" >&2
  exit 1
fi
echo "liveness ok ($first)"

CONFIG="$DOWNLOAD_DIR/curl_daily.cfg"
for pass in $(seq 1 "$MAX_PASSES"); do
  python3 "$PY" plan --inventory "$INVENTORY" --downloads "$DOWNLOAD_DIR" --config "$CONFIG"
  pending="$(grep -c '^url = ' "$CONFIG" || true)"
  if [ "$pending" = "0" ]; then
    echo "all files complete after pass=$pass"
    break
  fi
  echo "[$(date -Is)] pass=$pass fetching=$pending"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
    --continue-at - --parallel --parallel-max 4 \
    --user-agent "$UA" --config "$CONFIG" || echo "curl reported failures on pass=$pass; revalidating"
done
python3 "$PY" plan --inventory "$INVENTORY" --downloads "$DOWNLOAD_DIR" --config "$CONFIG"
if [ "$(grep -c '^url = ' "$CONFIG" || true)" != "0" ]; then
  echo "FATAL: downloads still incomplete after $MAX_PASSES passes" >&2
  exit 1
fi
rm -f "$CONFIG"

# Semantic check: every file must decode to valid xrsa_flux/xrsb_flux days.
python3 "$PY" check-downloads --inventory "$INVENTORY" --downloads "$DOWNLOAD_DIR"
echo "total_bytes=$(du -sb "$DOWNLOAD_DIR/daily" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
