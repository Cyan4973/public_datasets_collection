#!/usr/bin/env bash
# Documents how sources.tsv was resolved (metadata only; never fetches full files).
#  1. paginated anonymous S3 ListObjectsV2 of jwst/public/jw02736/jw02736001001/
#  2. 57,600-byte range probe of every NIRCam SW (nrca1-4, nrcb1-4) *_uncal.fits header
#  3. HEAD (x-amz-checksum-mode: ENABLED) of the selected files for version id + CRC64-NVME
#  4. scripts/discover.py checks the whole SW population and writes sources.tsv
# Scratch goes to $DISCOVER_DIR (default /tmp/autocollect/<id>/discover), not into the recipe.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="mast_jwst_nircam_sw_uncal_ramps_u16"
DISCOVER_DIR="${DISCOVER_DIR:-/tmp/autocollect/$DATASET_ID/discover}"
BUCKET="https://stpubdata.s3.amazonaws.com"
PREFIX="jwst/public/jw02736/jw02736001001/"
UA="openzl-public-datasets-jwst-nircam-uncal/1.0"
DISCOVER="$RECIPE_DIR/scripts/discover.py"

mkdir -p "$DISCOVER_DIR/listing" "$DISCOVER_DIR/hdr" "$DISCOVER_DIR/head"
rm -f "$DISCOVER_DIR"/listing/page_*.xml

page=0
cursor=""
while :; do
  page=$((page + 1))
  url="$BUCKET/?list-type=2&max-keys=1000&prefix=$PREFIX"
  if [[ -n "$cursor" ]]; then
    url="$url&continuation-token=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$cursor")"
  fi
  out="$DISCOVER_DIR/listing/page_$(printf %03d "$page").xml"
  curl --fail --silent --show-error --max-time 120 --retry 5 --user-agent "$UA" --output "$out" "$url"
  cursor="$(python3 "$DISCOVER" next-token "$out")"
  [[ -z "$cursor" ]] && break
done
python3 "$DISCOVER" candidates "$DISCOVER_DIR/listing" > "$DISCOVER_DIR/candidates.tsv"
echo "listing pages=$page sw_uncal_candidates=$(($(wc -l < "$DISCOVER_DIR/candidates.tsv") - 1))"

tail -n +2 "$DISCOVER_DIR/candidates.tsv" | cut -f1 | while read -r key; do
  name="${key##*/}"
  [[ -s "$DISCOVER_DIR/hdr/$name" ]] && continue
  curl --fail --silent --show-error --max-time 120 --retry 5 --range 0-57599 \
    --user-agent "$UA" --output "$DISCOVER_DIR/hdr/$name" "$BUCKET/$key"
done

python3 "$DISCOVER" selected | while read -r name; do
  curl --fail --silent --show-error --max-time 60 --retry 5 --head \
    --header 'x-amz-checksum-mode: ENABLED' --user-agent "$UA" \
    --output "$DISCOVER_DIR/head/$name.txt" "$BUCKET/$PREFIX$name"
done

python3 "$DISCOVER" finalize "$DISCOVER_DIR" "$RECIPE_DIR/sources.tsv"
