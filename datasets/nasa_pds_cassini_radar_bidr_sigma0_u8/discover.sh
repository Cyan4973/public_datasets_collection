#!/usr/bin/env bash
# Metadata-only discovery that produced sources.tsv (not part of the
# download/build/verify path). Lists every CORADR volume in the public
# asc-pds-cassini bucket, keeps BIBQH* Titan products from flybys T00A..T019,
# fetches each detached .LBL (~5 KB) and the last 1024 bytes of each .ZIP
# (central directory), and pins product geometry, sizes, ETag MD5s and the
# ZIP member CRC32. Output: $DISCOVER_DIR/sources.tsv (copy into the recipe).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISCOVER_DIR="${DISCOVER_DIR:-/tmp/autocollect/nasa_pds_cassini_radar_bidr_sigma0_u8/discover}"
BUCKET="https://asc-pds-cassini.s3.us-west-2.amazonaws.com/"
mkdir -p "$DISCOVER_DIR/listings" "$DISCOVER_DIR/meta"

fetch() {  # url out [range]
  local args=(--fail --silent --show-error --location --retry 5 --retry-delay 3 --max-time 120)
  [[ -n "${3:-}" ]] && args+=(--range "$3")
  curl "${args[@]}" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

fetch "${BUCKET}?list-type=2&prefix=RADAR/&delimiter=/" "$DISCOVER_DIR/radar_root.xml"
grep -q '<IsTruncated>false</IsTruncated>' "$DISCOVER_DIR/radar_root.xml"
grep -o '<Prefix>RADAR/CORADR_[0-9]*/</Prefix>' "$DISCOVER_DIR/radar_root.xml" \
  | sed -e 's#<Prefix>RADAR/##' -e 's#/</Prefix>##' > "$DISCOVER_DIR/volumes.txt"
echo "volumes=$(wc -l < "$DISCOVER_DIR/volumes.txt") (RADAR/superseded/ is not a CORADR volume and is ignored)"

while read -r volume; do
  out="$DISCOVER_DIR/listings/$volume.xml"
  [[ -s "$out" ]] || fetch "${BUCKET}?list-type=2&prefix=RADAR/$volume/DATA/BIDR/BIBQH" "$out"
done < "$DISCOVER_DIR/volumes.txt"

python3 "$RECIPE_DIR/scripts/discover.py" select \
  --listings "$DISCOVER_DIR/listings" --out "$DISCOVER_DIR/selected.tsv"

tail -n +2 "$DISCOVER_DIR/selected.tsv" | while IFS=$'\t' read -r volume product _rest; do
  base="${BUCKET}RADAR/$volume/DATA/BIDR/$product"
  [[ -s "$DISCOVER_DIR/meta/$product.LBL" ]] || fetch "$base.LBL" "$DISCOVER_DIR/meta/$product.LBL"
  [[ -s "$DISCOVER_DIR/meta/$product.ZIP.tail" ]] || fetch "$base.ZIP" "$DISCOVER_DIR/meta/$product.ZIP.tail" "-1024"
done

python3 "$RECIPE_DIR/scripts/discover.py" pin \
  --selected "$DISCOVER_DIR/selected.tsv" --meta "$DISCOVER_DIR/meta" --out "$DISCOVER_DIR/sources.tsv"
sha256sum "$DISCOVER_DIR/sources.tsv"
