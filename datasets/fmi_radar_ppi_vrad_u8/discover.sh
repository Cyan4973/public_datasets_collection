#!/usr/bin/env bash
# Metadata-only discovery: documents how sources.tsv was resolved.
#
# 1. HEAD every candidate object
#      <YYYY>/<MM>/<DD>/fikor/<YYYYMMDD><HH>00_fikor_ppi_0.5_vrad_qc.tif
#    for every day 2025-03-01 .. 2026-03-31 (the "Rack_fmi.fi 10.7" processing
#    window) at the four synoptic hours 00, 06, 12, 18 UTC, recording status,
#    Content-Length, ETag (single-part MD5), Last-Modified and S3 version id.
#    No payload bytes are fetched.
# 2. Rank candidates (scripts/fmivrad.py rank): per day keep the largest of the
#    four scans (LZW file size is a proxy for echo coverage); per month order
#    those day-best scans by size, largest first, with a minimum size.
# 3. For the ranked scans, fetch only the TIFF header (bytes 0-4095, a range
#    request) and check the pinned layout, GDAL scale/offset/nodata and the
#    "Rack_fmi.fi 10.7" Software tag (scripts/fmivrad.py check-header
#    --header-only); keep the first PER_MONTH passing scans per month, skipping
#    any scan on the same or an adjacent calendar day as an already chosen one
#    (scripts/fmivrad.py select), so the scans are at least two days apart.
# HEADs are retried; only 200 and 404 count as final answers, and discovery
# fails if any HEAD stays unresolved.
#
# Output: sources.tsv.new (for review) plus the full HEAD inventory. The
# committed sources.tsv is what download.sh enforces; nothing here is run by
# download.sh, build.sh or verify.sh.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="https://fmi-opendata-radar-geotiff.s3.amazonaws.com"
OUT_DIR="${DISCOVER_OUT_DIR:-$RECIPE_DIR}"
WORK="$OUT_DIR/discover_work"
UA="openzl-public-datasets-fmi-vrad-discover/1.0"
FIRST_DAY="2025-03-01"
LAST_DAY="2026-03-31"
PER_MONTH="${PER_MONTH:-6}"
MIN_SIZE="${MIN_SIZE:-200000}"
HEAD_RANK_DEPTH="${HEAD_RANK_DEPTH:-20}"

mkdir -p "$WORK/headers"

head_one() {  # key -> one TSV line: key status size etag last_modified version_id
  local key="$1" raw hdr status size etag lm vid
  if raw="$(curl --globoff --silent --show-error --head --retry 8 --retry-delay 3 --retry-all-errors \
      --max-time 60 --user-agent "openzl-public-datasets-fmi-vrad-discover/1.0" \
      "https://fmi-opendata-radar-geotiff.s3.amazonaws.com/$key")"; then
    hdr="$(printf '%s\n' "$raw" | tr -d '\r')"
  else
    printf '%s\tERR\t\t\t\t\n' "$key"
    return 0
  fi
  # a forward proxy may prepend its own "HTTP/1.1 200 Connection established" block
  status="$(printf '%s\n' "$hdr" | awk '/^HTTP\//{code=$2} END{print code}')"
  size="$(printf '%s\n' "$hdr" | awk -F': ' 'tolower($1)=="content-length"{v=$2} END{print v}')"
  etag="$(printf '%s\n' "$hdr" | awk -F': ' 'tolower($1)=="etag"{v=$2} END{print v}' | tr -d '"')"
  lm="$(printf '%s\n' "$hdr" | awk -F': ' 'tolower($1)=="last-modified"{v=$2} END{print v}')"
  vid="$(printf '%s\n' "$hdr" | awk -F': ' 'tolower($1)=="x-amz-version-id"{v=$2} END{print v}')"
  if [[ "$status" == "200" && ( -z "$size" || -z "$etag" || -z "$vid" ) ]]; then
    status="ERR"  # proxy CONNECT block only, or an incomplete S3 response
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$key" "${status:-ERR}" "$size" "$etag" "$lm" "$vid"
}
export -f head_one

# 1. HEAD inventory
keys="$WORK/candidate_keys.txt"
: > "$keys"
day="$FIRST_DAY"
while [[ "$day" < "$LAST_DAY" || "$day" == "$LAST_DAY" ]]; do
  ymd="${day//-/}"
  for hh in 00 06 12 18; do
    printf '%s/%s/%s/fikor/%s%s00_fikor_ppi_0.5_vrad_qc.tif\n' "${day:0:4}" "${day:5:2}" "${day:8:2}" "$ymd" "$hh" >> "$keys"
  done
  day="$(date -u -d "$day + 1 day" +%F)"
done
inventory="$OUT_DIR/discover_inventory.tsv"
printf 'key\tstatus\tsize_bytes\tetag\tlast_modified\tversion_id\n' > "$inventory"
xargs -P 8 -I{} bash -c 'head_one "$1"' _ {} < "$keys" | sort > "$WORK/inventory.body"
# re-try unresolved rows serially; only 200 and 404 are accepted as final answers
for pass in 1 2 3; do
  awk -F'\t' '$2!="200" && $2!="404"{print $1}' "$WORK/inventory.body" > "$WORK/retry_keys.txt"
  [[ -s "$WORK/retry_keys.txt" ]] || break
  echo "retry pass $pass: $(wc -l < "$WORK/retry_keys.txt") unresolved HEADs"
  sleep 10
  awk -F'\t' '$2=="200" || $2=="404"' "$WORK/inventory.body" > "$WORK/inventory.keep"
  while read -r key; do head_one "$key"; done < "$WORK/retry_keys.txt" >> "$WORK/inventory.keep"
  sort "$WORK/inventory.keep" > "$WORK/inventory.body"
done
unresolved="$(awk -F'\t' '$2!="200" && $2!="404"' "$WORK/inventory.body" | wc -l)"
[[ "$unresolved" == "0" ]] || { echo "discovery incomplete: $unresolved HEADs unresolved" >&2; exit 1; }
[[ "$(wc -l < "$WORK/inventory.body")" == "$(wc -l < "$keys")" ]] || { echo "inventory row count mismatch" >&2; exit 1; }
cat "$WORK/inventory.body" >> "$inventory"
echo "inventory rows=$(($(wc -l < "$inventory") - 1)) ok=$(awk -F'\t' '$2=="200"' "$inventory" | wc -l) missing_404=$(awk -F'\t' '$2=="404"' "$inventory" | wc -l)"

# 2. rank
ranked="$WORK/ranked.tsv"
python3 "$RECIPE_DIR/scripts/fmivrad.py" rank --inventory "$inventory" --min-size "$MIN_SIZE" \
  --depth "$HEAD_RANK_DEPTH" > "$ranked"

# 3. header-only checks for the ranked scans, then keep PER_MONTH per month
checked="$WORK/checked.tsv"
: > "$checked"
while IFS=$'\t' read -r month rank key size etag lm vid; do
  [[ "$month" != "month" ]] || continue
  hfile="$WORK/headers/$(basename "$key").hdr"
  if [[ ! -s "$hfile" ]]; then
    curl --globoff --fail --silent --show-error --range 0-4095 --retry 5 --retry-delay 2 --max-time 60 \
      --user-agent "$UA" --output "$hfile" "$BASE/$key?versionId=$vid"
  fi
  if software="$(python3 "$RECIPE_DIR/scripts/fmivrad.py" check-header --header-only "$hfile" "$key")"; then
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tok\t%s\n' "$month" "$rank" "$key" "$size" "$etag" "$lm" "$vid" "$software" >> "$checked"
  else
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tfail\t-\n' "$month" "$rank" "$key" "$size" "$etag" "$lm" "$vid" >> "$checked"
  fi
done < "$ranked"

python3 "$RECIPE_DIR/scripts/fmivrad.py" select --checked "$checked" --per-month "$PER_MONTH" \
  --base "$BASE" > "$OUT_DIR/sources.tsv.new"
echo "wrote $OUT_DIR/sources.tsv.new rows=$(($(wc -l < "$OUT_DIR/sources.tsv.new") - 1))"
