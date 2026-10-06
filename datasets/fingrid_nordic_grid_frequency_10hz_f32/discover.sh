#!/usr/bin/env bash
# Resolve the pinned monthly archives and their 7z member lists with small
# metadata requests only (dataset page, HEAD, and three byte ranges per
# archive: start header, next header, packed header).  Writes sources.tsv and
# members.tsv into OUT_DIR for review; the committed copies live next to this
# script.  Never fetches archive payloads.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="fingrid_nordic_grid_frequency_10hz_f32"
OUT_DIR="${OUT_DIR:-/tmp/autocollect/$DATASET_ID/discover}"
PAGE_URL="https://data.fingrid.fi/en/datasets/339"
# Months without a DST transition (Finnish local time), spread over two
# winters and one summer.  Only 2025+ months: the 2024 archives contain
# hour-aligned stretches from a smoothed 1 mHz backup measurement chain
# (see README, "Measurement chain and resolution rule").
MONTHS=(2025-01 2025-07 2026-01)
TOOL="$RECIPE_DIR/scripts/fingrid_frequency.py"
UA="openzl-public-datasets-fingrid-frequency/1.0"

mkdir -p "$OUT_DIR"
curl -fsSL --retry 3 --max-time 120 --max-filesize 10000000 -A "$UA" -o "$OUT_DIR/dataset_339.html" "$PAGE_URL"

printf 'month\tfilename\turl\tsize_bytes\tcontent_md5_b64\tlast_modified_http\tsha256\n' > "$OUT_DIR/sources.tsv"
printf 'month\tmember\tsize_bytes\tcrc32\n' > "$OUT_DIR/members.tsv"

python3 "$TOOL" page-listing --page "$OUT_DIR/dataset_339.html" "${MONTHS[@]}" > "$OUT_DIR/listing.tsv"
if [ "$(wc -l < "$OUT_DIR/listing.tsv")" -ne "${#MONTHS[@]}" ]; then
  echo "FATAL: dataset page does not list every requested month" >&2
  exit 1
fi

while IFS=$'\t' read -r month url listed_size; do
  name="$(basename "$url")"
  headers="$OUT_DIR/$month.head"
  curl -fsSIL --max-time 60 -A "$UA" "$url" | tr -d '\r' > "$headers"
  length="$(awk -F': ' 'tolower($1)=="content-length"{v=$2} END{print v}' "$headers")"
  md5="$(awk -F': ' 'tolower($1)=="content-md5"{v=$2} END{print v}' "$headers")"
  modified="$(awk -F': ' 'tolower($1)=="last-modified"{v=$2} END{print v}' "$headers")"
  if [ "$length" != "$listed_size" ] || [ -z "$md5" ]; then
    echo "FATAL: $url HEAD length=$length listed=$listed_size md5=$md5" >&2
    exit 1
  fi
  curl -fsSL --max-time 60 -A "$UA" -r 0-31 -o "$OUT_DIR/$month.start" "$url"
  next_range="$(python3 "$TOOL" discover-members --month "$month" --start "$OUT_DIR/$month.start" --print-ranges next)"
  curl -fsSL --max-time 60 -A "$UA" -r "$next_range" -o "$OUT_DIR/$month.next" "$url"
  packed_range="$(python3 "$TOOL" discover-members --month "$month" --start "$OUT_DIR/$month.start" \
    --next "$OUT_DIR/$month.next" --print-ranges packed)"
  curl -fsSL --max-time 60 -A "$UA" -r "$packed_range" -o "$OUT_DIR/$month.packed" "$url"
  python3 "$TOOL" discover-members --month "$month" --start "$OUT_DIR/$month.start" \
    --next "$OUT_DIR/$month.next" --packed "$OUT_DIR/$month.packed" >> "$OUT_DIR/members.tsv"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t-\n' "$month" "$name" "$url" "$length" "$md5" "$modified" >> "$OUT_DIR/sources.tsv"
done < "$OUT_DIR/listing.tsv"

echo "wrote $OUT_DIR/sources.tsv and $OUT_DIR/members.tsv"
