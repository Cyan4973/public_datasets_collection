#!/usr/bin/env bash
# Resolve the pinned inventory (scripts/inventory.tsv) for the recipe: fetch
# the 60 monthly S3 ListObjectsV2 pages for 2020-01..2024-12 of the public
# NOAA OISST v2.1 bucket, require each month to be complete and final (no
# '_preliminary' objects), and record date, key, size and MD5 ETag of the
# files dated the 1st and 15th.  Run once by the recipe author; download.sh
# does not need it.  The printed SHA-256 must be pinned in scripts/oisst_sst.py.
#
# Usage: bash discover.sh [LISTING_DIR]   (default /tmp/autocollect/noaa_cdr_oisst_v21_sst_i16/listings)
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LISTING_DIR="${1:-/tmp/autocollect/noaa_cdr_oisst_v21_sst_i16/listings}"
BASE_URL="https://noaa-cdr-sea-surface-temp-optimum-interpolation-pds.s3.amazonaws.com"
mkdir -p "$LISTING_DIR"

for year in 2020 2021 2022 2023 2024; do
  for month in 01 02 03 04 05 06 07 08 09 10 11 12; do
    out="$LISTING_DIR/$year$month.xml"
    [ -s "$out" ] && continue
    curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
      --retry-all-errors --max-time 120 --output "$out.part" \
      "$BASE_URL/?list-type=2&prefix=data/v2.1/avhrr/$year$month/"
    mv "$out.part" "$out"
  done
done

python3 "$RECIPE_DIR/scripts/oisst_sst.py" inventory --listings "$LISTING_DIR" \
  --out "$RECIPE_DIR/scripts/inventory.tsv"
