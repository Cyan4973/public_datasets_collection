#!/usr/bin/env bash
# Documentation of how sources.tsv was produced (not part of download/build).
#
# 1. Fetch the work-unit VPC and the official link list from the prd-tnm bucket.
# 2. Apply the selection rule (scripts/cpk_tiles.py select).
# 3. Range-GET the first 8 KiB of every selected tile from rockyweb (LAS
#    header + VLRs; point data starts at byte 1750) and record size, ETag,
#    Last-Modified, header creation day and the 15 extended points-by-return
#    counts in sources.tsv. The sha256 column is filled from the first full
#    driver download.
# Usage: bash discover.sh [WORK_DIR]   (default /tmp/autocollect/<id>/discover)
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="usgs_3dep_cameronpeak_vq1560ii_scan_angle_i16"
WORK="${1:-/tmp/autocollect/$DATASET_ID/discover}"
S3="https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/CO_CameronPeakWildfire_2021_D21/CO_CameronPkFire_1_2021"
TOOL="$RECIPE_DIR/scripts/cpk_tiles.py"
CURL=(curl --fail --silent --show-error --location --retry 8 --retry-delay 5 --retry-all-errors --max-time 120)

mkdir -p "$WORK/meta" "$WORK/probe"
[ -s "$WORK/meta/project.vpc" ] || "${CURL[@]}" -o "$WORK/meta/project.vpc" "$S3/CO_CameronPkFire_1_2021.vpc"
[ -s "$WORK/meta/links.txt" ] || "${CURL[@]}" -o "$WORK/meta/links.txt" "$S3/0_file_download_links.txt"
sha256sum "$WORK/meta/project.vpc" "$WORK/meta/links.txt"

python3 -I "$TOOL" select --vpc "$WORK/meta/project.vpc" --links "$WORK/meta/links.txt" > "$WORK/selection.tsv"
tail -n +2 "$WORK/selection.tsv" | while IFS=$'\t' read -r tile_id _count _dt _name url; do
  [ -s "$WORK/probe/$tile_id.bin" ] && [ "$(stat -c %s "$WORK/probe/$tile_id.bin")" = 8192 ] && continue
  for attempt in 1 2 3 4 5 6; do
    if "${CURL[@]}" --range 0-8191 --dump-header "$WORK/probe/$tile_id.headers" \
         -o "$WORK/probe/$tile_id.bin" "$url" < /dev/null \
       && [ "$(stat -c %s "$WORK/probe/$tile_id.bin")" = 8192 ]; then
      break
    fi
    echo "probe retry $tile_id attempt=$attempt" >&2
    sleep $((attempt * 10))
  done
done
python3 -I "$TOOL" make-sources --vpc "$WORK/meta/project.vpc" --links "$WORK/meta/links.txt" \
  --probe-dir "$WORK/probe" --out "$WORK/sources.tsv"
echo "review $WORK/sources.tsv and copy it to $RECIPE_DIR/sources.tsv"
