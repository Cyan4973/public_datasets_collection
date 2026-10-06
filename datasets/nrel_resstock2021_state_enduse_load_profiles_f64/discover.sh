#!/usr/bin/env bash
# Documents how sources.tsv was produced (run once on 2026-10-06; not part of
# the download path). Lists the release's timeseries_aggregates/by_state/
# prefix with one anonymous S3 ListObjectsV2 request (244 keys, one page) and
# pins state, key, size, single-part ETag (md5) and LastModified of the 49
# <xx>-single-family_detached.csv objects (48 states + DC; no AK or HI).
# download.sh re-checks the live listing against these pins on every run.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUCKET="https://oedi-data-lake.s3.amazonaws.com"
RELEASE="nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2021/resstock_amy2018_release_1"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export PYTHONDONTWRITEBYTECODE=1

curl --fail --silent --show-error --location --retry 5 --max-time 120 \
  --output "$WORK/listing.xml" "$BUCKET/?list-type=2&prefix=$RELEASE/timeseries_aggregates/by_state/"
python3 "$RECIPE_DIR/scripts/resstock.py" discover --listing "$WORK/listing.xml" --out "$RECIPE_DIR/sources.tsv"
