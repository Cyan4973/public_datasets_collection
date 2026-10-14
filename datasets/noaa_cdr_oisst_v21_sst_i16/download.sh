#!/usr/bin/env bash
# Download the 120 pinned NOAA OISST v2.1 (AVHRR-only, final) daily NetCDF4
# files dated the 1st and 15th of every month 2020-2024 from the public NOAA
# Open Data Dissemination S3 bucket.  Anonymous HTTPS only.  Every file must
# match the size and MD5 (single-part S3 ETag) pinned in scripts/inventory.tsv,
# whose SHA-256 is pinned in scripts/oisst_sst.py, and must decode to a valid
# sst grid.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="noaa_cdr_oisst_v21_sst_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://noaa-cdr-sea-surface-temp-optimum-interpolation-pds.s3.amazonaws.com"
MAX_PASSES=6
UA="openzl-public-datasets-noaa-oisst/1.0"
PY="$RECIPE_DIR/scripts/oisst_sst.py"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

CONFIG="$DOWNLOAD_DIR/curl_nc.cfg"
done_ok=0
for pass in $(seq 1 "$MAX_PASSES"); do
  python3 "$PY" plan --downloads "$DOWNLOAD_DIR" --base-url "$BASE_URL" --config "$CONFIG"
  pending="$(grep -c '^url = ' "$CONFIG" || true)"
  if [ "$pending" = "0" ]; then
    echo "all files present and valid after pass=$pass"
    done_ok=1
    break
  fi
  echo "[$(date -Is)] pass=$pass fetching=$pending"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
    --continue-at - --parallel --parallel-max 6 \
    --user-agent "$UA" --config "$CONFIG" || echo "curl reported failures on pass=$pass; revalidating"
done
if [ "$done_ok" != "1" ]; then
  python3 "$PY" plan --downloads "$DOWNLOAD_DIR" --base-url "$BASE_URL" --config "$CONFIG"
  if [ "$(grep -c '^url = ' "$CONFIG" || true)" != "0" ]; then
    echo "FATAL: still incomplete after $MAX_PASSES passes" >&2
    exit 1
  fi
fi
rm -f "$CONFIG"

# Semantic check: every file decodes to a valid OISST v2.1 final sst grid.
python3 "$PY" check-downloads --downloads "$DOWNLOAD_DIR"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
