#!/usr/bin/env bash
# Documents how sources.tsv was resolved (not part of the download/build path).
#
#   WORK=/tmp/geiger_discover bash discover.sh > sources.tsv
#
# 1. Fetch the project VPC (STAC FeatureCollection with per-tile pc:count and
#    datetime) and the official link list from the USGS prd-tnm S3 bucket.
# 2. Apply the selection rule in scripts/geiger_tiles.py (VPC datetime
#    2016-08-10 and pc:count < 9,000,000, sorted by tile id).
# 3. Range-GET the first 469 bytes (LAS 1.4 header + LASzip VLR) of every
#    selected tile from rockyweb.usgs.gov to pin size, ETag, Last-Modified and
#    header X bounds, and to assert the sensor/scale/offset/format invariants.
# The sha256 column stays empty here; it is filled from the first full
# download (download.sh records digests in downloads/<id>/meta/sha256.tsv).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${WORK:-/tmp/autocollect/usgs_3dep_nc_geiger_laz_x_i32/discover}"
S3="https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/NC_Phase_4_CentralWestNC_GEIGER_A16/NC_Phase4_Anson_2016"
CURL=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors --max-time 300)
mkdir -p "$WORK/probe"

"${CURL[@]}" -o "$WORK/NC_Phase4_Anson_2016.vpc" "$S3/NC_Phase4_Anson_2016.vpc"
"${CURL[@]}" -o "$WORK/0_file_download_links.txt" "$S3/0_file_download_links.txt"

python3 "$RECIPE_DIR/scripts/geiger_tiles.py" select --vpc "$WORK/NC_Phase4_Anson_2016.vpc" \
  --links "$WORK/0_file_download_links.txt" > "$WORK/selection.tsv"

while IFS=$'\t' read -r tile_id pc_count vpc_datetime file_name url; do
  [ "$tile_id" = "tile_id" ] && continue
  for attempt in 1 2 3 4 5; do
    if "${CURL[@]}" --range 0-468 --dump-header "$WORK/probe/$tile_id.headers" \
        -o "$WORK/probe/$tile_id.bin" "$url" < /dev/null; then
      break
    fi
    sleep $((attempt * 5))
  done
done < "$WORK/selection.tsv"

python3 "$RECIPE_DIR/scripts/geiger_tiles.py" make-sources --vpc "$WORK/NC_Phase4_Anson_2016.vpc" \
  --links "$WORK/0_file_download_links.txt" --probe-dir "$WORK/probe"
