#!/usr/bin/env bash
# Discovery helper (NOT part of the acceptance path; documents how sources.tsv
# was resolved on 2026-10-08).
#
# 1. Enumerate every burst's payload_N000.dng in the full HDR+ dataset
#    (gs://hdrplusdata/20171106/bursts/, 3640 bursts) through the anonymous
#    GCS JSON API, using matchGlob and pageToken pagination.
# 2. Range-GET the first 4 KiB of every N000 frame (IFD0 of the HDR+ LJ92
#    writer sits at offset 8; legacy uncompressed writers put IFD0 at the end
#    of the file and therefore fail the probe, which is the intended result).
# 3. scripts/select_bursts.py classifies each burst from IFD0 and writes
#    candidates.tsv plus a deterministic evenly spaced selection
#    (sources.candidate.tsv).
# 4. scripts/gallery_thumbs.sh fetches the first 32 KiB of each selected
#    burst's gallery JPEG and extracts the embedded EXIF thumbnail for the
#    human-review privacy screen recorded in sources.tsv / README.md.
#
# Output goes to $DATA_DIR/discovery/<id>/. Total traffic is about 16 MB.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="google_hdrplus_pixel_raw_bayer_u16"
OUT="$DATA_ROOT/discovery/$DATASET_ID"
PREFIX="${HDRPLUS_PREFIX:-20171106/bursts/}"
API="https://storage.googleapis.com/storage/v1/b/hdrplusdata/o"
mkdir -p "$OUT/headers"

page=0
page_cursor=""
rm -f "$OUT"/listing_*.json
while :; do
  url="$API?prefix=${PREFIX}&matchGlob=**/payload_N000.dng&maxResults=1000&fields=nextPageToken,items(name,size,md5Hash,generation,updated)"
  [ -n "$page_cursor" ] && url="$url&pageToken=$page_cursor"
  curl -fsS --retry 5 --max-time 120 -o "$OUT/listing_$page.json" "$url"
  page_cursor="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("nextPageToken",""))' "$OUT/listing_$page.json")"
  page=$((page + 1))
  [ -n "$page_cursor" ] || break
done

python3 -I - "$OUT" <<'PY' > "$OUT/n000_keys.txt"
import glob, json, sys
for f in sorted(glob.glob(sys.argv[1] + "/listing_*.json")):
    for it in json.load(open(f)).get("items", []):
        if it["name"].endswith("/payload_N000.dng"):
            print(it["name"])
PY
echo "listing_pages=$page n000_frames=$(wc -l < "$OUT/n000_keys.txt")"

export OUT
xargs -P 8 -I{} bash -c '
  key="{}"; burst="$(basename "$(dirname "$key")")"; h="$OUT/headers/$burst.bin"
  [ -s "$h" ] && exit 0
  curl -fsS --retry 5 --max-time 120 -r 0-4095 -o "$h.part" "https://storage.googleapis.com/hdrplusdata/$key" && mv "$h.part" "$h"
' < "$OUT/n000_keys.txt"
echo "headers=$(ls "$OUT/headers" | grep -c '\.bin$')"

python3 -I "$RECIPE_DIR/scripts/select_bursts.py" "$OUT" "${HDRPLUS_SELECT_N:-40}"
