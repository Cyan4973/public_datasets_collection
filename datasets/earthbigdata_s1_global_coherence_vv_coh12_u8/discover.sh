#!/usr/bin/env bash
# Metadata-only discovery: documents how sources.tsv was resolved.
#
# For every 1x1-degree tile in the pinned contiguous block
#   rows N36..N45 (upper-left latitude label) x columns W100..W114,
# send one HEAD request for <TILE>_summer_vv_COH12.tif and record the object
# size, S3 ETag (single-part MD5) and Last-Modified header. No payload bytes
# are fetched. The output is written to sources.tsv.new for review; the
# committed sources.tsv is what download.sh enforces.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="https://sentinel-1-global-coherence-earthbigdata.s3.us-west-2.amazonaws.com"
OUT="$RECIPE_DIR/sources.tsv.new"
UA="openzl-public-datasets-earthbigdata-coherence-discover/1.0"

printf 'tile\tfilename\tsize_bytes\tmd5\tlast_modified\turl\n' > "$OUT"
missing=0
for lat in $(seq 45 -1 36); do
  for lon in $(seq 114 -1 100); do
    tile="$(printf 'N%02dW%03d' "$lat" "$lon")"
    fname="${tile}_summer_vv_COH12.tif"
    url="$BASE/data/tiles/$tile/$fname"
    headers="$(curl --globoff --silent --show-error --head --location \
      --retry 5 --retry-delay 2 --max-time 60 --user-agent "$UA" "$url" | tr -d '\r')"
    status="$(printf '%s\n' "$headers" | awk '/^HTTP\//{code=$2} END{print code}')"
    if [[ "$status" != "200" ]]; then
      echo "missing tile=$tile status=$status" >&2
      missing=$((missing + 1))
      continue
    fi
    size="$(printf '%s\n' "$headers" | awk -F': ' 'tolower($1)=="content-length"{v=$2} END{print v}')"
    etag="$(printf '%s\n' "$headers" | awk -F': ' 'tolower($1)=="etag"{v=$2} END{print v}' | tr -d '"')"
    lm="$(printf '%s\n' "$headers" | awk -F': ' 'tolower($1)=="last-modified"{v=$2} END{print v}')"
    [[ "$etag" =~ ^[0-9a-f]{32}$ ]] || { echo "non-MD5 ETag tile=$tile etag=$etag" >&2; exit 1; }
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$tile" "$fname" "$size" "$etag" "$lm" "$url" >> "$OUT"
  done
done
echo "wrote $OUT rows=$(($(wc -l < "$OUT") - 1)) missing=$missing"
