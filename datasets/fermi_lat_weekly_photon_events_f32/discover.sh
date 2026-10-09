#!/usr/bin/env bash
# Documentation of how sources.tsv was resolved. Not part of the download/build
# contract: download.sh only reads the pinned sources.tsv.
#
# 1. Fetch the HEASARC directory listing of the LAT weekly photon files.
# 2. scripts/select_weeks.py picks N evenly spaced weeks out of w010..w950.
# 3. Per selected file: HTTP HEAD (Content-Length, Last-Modified), a 28,800-byte
#    prefix range GET (primary + EVENTS headers) and a 28,800-byte suffix range
#    GET (GTI header). select_weeks.py pin validates the schema, checks that
#    the FITS layout adds up to the exact Content-Length, and writes the table.
#
# Usage: bash discover.sh [OUT_DIR] [N]   (default /tmp/autocollect/<id>/discover, 20)
set -euo pipefail

DATASET_ID="fermi_lat_weekly_photon_events_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-/tmp/autocollect/$DATASET_ID/discover}"
COUNT="${2:-20}"
BASE="https://heasarc.gsfc.nasa.gov/FTP/fermi/data/lat/weekly/photon"
UA="openzl-public-datasets-fermi-lat-weekly/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$OUT_DIR/probes"
curl -fsS --retry 5 --retry-delay 3 --max-time 120 -A "$UA" -o "$OUT_DIR/listing.html" "$BASE/"
python3 "$RECIPE_DIR/scripts/select_weeks.py" targets "$OUT_DIR/listing.html" "$COUNT" > "$OUT_DIR/targets.txt"
while read -r name; do
  curl -fsSI --retry 5 --retry-delay 3 --max-time 60 -A "$UA" -o "$OUT_DIR/probes/$name.head" "$BASE/$name"
  curl -fsS --retry 5 --retry-delay 3 --max-time 120 -A "$UA" -r 0-28799 -o "$OUT_DIR/probes/$name.prefix" "$BASE/$name"
  curl -fsS --retry 5 --retry-delay 3 --max-time 120 -A "$UA" -r -28800 -o "$OUT_DIR/probes/$name.tail" "$BASE/$name"
  echo "probed $name"
done < "$OUT_DIR/targets.txt"
python3 "$RECIPE_DIR/scripts/select_weeks.py" pin "$OUT_DIR/listing.html" "$COUNT" "$OUT_DIR/probes" \
  "$OUT_DIR/sources.selected.tsv"
echo "selected inventory: $OUT_DIR/sources.selected.tsv (copy to $RECIPE_DIR/sources.tsv)"
