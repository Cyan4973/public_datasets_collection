#!/usr/bin/env bash
# Re-resolve sources.tsv from the live bucket (metadata only: one S3 listing
# page and the 2.95 MB STAC item collection). Not part of the acceptance path;
# documents how the pinned tile list was produced (2026-10-08).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-/tmp/autocollect/noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64/discover}"
BASE="https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com"
mkdir -p "$OUT_DIR"

curl -fsS --max-time 120 -o "$OUT_DIR/listing.xml" \
  "$BASE/?list-type=2&prefix=laz/geoid18/8526/"
curl -fsS --max-time 300 -o "$OUT_DIR/stac_items.json" \
  "$BASE/laz/geoid18/8526/stac/noaa_copc_item_collection_m8526.json"
python3 -I "$RECIPE_DIR/scripts/discover_sources.py" \
  "$OUT_DIR/listing.xml" "$OUT_DIR/stac_items.json" "$OUT_DIR/sources.tsv"
echo "compare: diff $OUT_DIR/sources.tsv $RECIPE_DIR/sources.tsv (sha256 column is filled only in the pinned copy)"
