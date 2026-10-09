#!/usr/bin/env bash
# Download the 36 pinned MBARI MARS daily hybrid-millidecade NetCDF4 files
# listed in days.tsv from the public pacific-sound-spectra S3 bucket.
#
# Whole files are fetched (16,124,324 B each; the psd span is 16,053,120 B,
# i.e. 99.56% of each file) so that every object can be checked against its
# pinned S3 multipart ETag and the HDF5 metadata can be parsed in full.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ;; *) DATA_DIR="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mbari_mars_hydrophone_hmd_psd_f32"
BUCKET_URL="https://pacific-sound-spectra.s3.amazonaws.com"
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
DAYS_TSV="$RECIPE_DIR/days.tsv"
EXPECTED_FILES=36
FILE_SIZE=16124324
UA="openzl-public-datasets-mbari-mars-hmd/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

rows="$(tail -n +2 "$DAYS_TSV" | grep -c .)"
if [ "$rows" != "$EXPECTED_FILES" ]; then
  echo "FATAL: days.tsv has $rows rows, expected $EXPECTED_FILES" >&2
  exit 1
fi

# Liveness: one-byte range GET of the first pinned object.
first_key="$(tail -n +2 "$DAYS_TSV" | head -n 1 | cut -f1)"
probe="$(curl -fsSL --max-time 60 --retry 3 -r 0-0 -A "$UA" "$BUCKET_URL/$first_key" | od -An -tx1 | tr -d ' \n')"
if [ "$probe" != "89" ]; then
  echo "FATAL: liveness probe of $first_key returned '$probe' (expected HDF5 signature byte 89)" >&2
  exit 1
fi

n=0
tail -n +2 "$DAYS_TSV" | while IFS=$'\t' read -r key size etag _rest; do
  n=$((n + 1))
  [ "$size" = "$FILE_SIZE" ] || { echo "FATAL: days.tsv size for $key is $size" >&2; exit 1; }
  case "$key" in
    20[12][0-9]/MARS_20[12][0-9][01][0-9][0-3][0-9].nc) ;;
    *) echo "FATAL: unexpected key $key" >&2; exit 1 ;;
  esac
  name="$(basename "$key")"
  dest="$DOWNLOAD_DIR/$name"
  if [ -f "$dest" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if python3 -I "$RECIPE_DIR/scripts/validate_download.py" "$dest" "$key" "$etag"; then
      echo "[$n/$EXPECTED_FILES] cache_hit $key"
      continue
    fi
    echo "[$n/$EXPECTED_FILES] cached file invalid, refetching $key"
    rm -f "$dest"
  fi
  part="$dest.part"
  if [ -f "$part" ] && [ "$(wc -c < "$part" | tr -d ' ')" -gt "$FILE_SIZE" ]; then
    rm -f "$part"
  fi
  if [ ! -f "$part" ] || [ "$(wc -c < "$part" | tr -d ' ')" != "$FILE_SIZE" ]; then
    curl -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --max-filesize "$((FILE_SIZE + 1))" -A "$UA" \
      -sS -o "$part" "$BUCKET_URL/$key"
  fi
  if ! python3 -I "$RECIPE_DIR/scripts/validate_download.py" "$part" "$key" "$etag"; then
    echo "FATAL: $key failed validation; removing partial file" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$dest"
  echo "[$n/$EXPECTED_FILES] fetched $key"
done

count="$(find "$DOWNLOAD_DIR" -maxdepth 1 -name 'MARS_*.nc' | wc -l | tr -d ' ')"
if [ "$count" != "$EXPECTED_FILES" ]; then
  echo "FATAL: $count validated files present, expected $EXPECTED_FILES" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$((count * FILE_SIZE))"
