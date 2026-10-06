#!/usr/bin/env bash
# Resolve and pin the 36 Sagamore Hill 2024 SRS day files listed in
# sources.tsv. Metadata only: 12 directory listings plus, per candidate file,
# one 32 KiB head range (first ~40 sweep records, headers checked) and one
# 8-byte tail range (gzip trailer CRC32 + ISIZE, plus Content-Range total
# size and Last-Modified). No full files are fetched.
#
# Selection rule: requested days are the 1st, 11th and 21st of every month of
# 2024. For each requested day d the first file among d, d+1, ..., d+9 (same
# month) that exists and passes the probe is taken. A probe passes when the
# gzip ISIZE is a multiple of 826 bytes with >= 5000 records and every
# head-range record has site 5, 2 bands, band descriptors (25,75,401,20,0) and
# (75,180,401,20,0), and the file's own date. The sha256 column is written as
# '-' (not yet pinned); it is pinned from the first full driver download.
#
# Usage: bash discover.sh [OUT_TSV]   (default: sources.tsv next to this file)
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$RECIPE_DIR/sources.tsv}"
HELPER="$RECIPE_DIR/scripts/srs.py"
BASE="https://www.ngdc.noaa.gov/stp/space-weather/solar-data/solar-features/solar-radio/rstn-spectral/sagamore-hill"
YEAR=2024
UA="openzl-public-datasets-rstn-srs/1.0"
TMP="$(mktemp -d /tmp/rstn_srs_discover.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

curl_small() {
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
    --connect-timeout 30 --max-time 120 --user-agent "$UA" "$@"
}

printf 'requested_date\tselected_date\tfilename\turl\tsize_bytes\tlast_modified\tgzip_crc32\tgzip_isize\trecords\tfirst_sweep_utc\tsha256\n' > "$OUT.tmp"
for month in $(seq 1 12); do
  mm="$(printf '%02d' "$month")"
  listing="$TMP/listing_$mm.html"
  curl_small --output "$listing" "$BASE/$YEAR/$mm/"
  python3 "$HELPER" parse-listing --html "$listing" --year "$YEAR" --month "$month" > "$TMP/names_$mm.txt"
  for d0 in 1 11 21; do
    requested="$(printf '%04d-%s-%02d' "$YEAR" "$mm" "$d0")"
    chosen=""
    for d in $(seq "$d0" $((d0 + 9))); do
      dd="$(printf '%02d' "$d")"
      name="k7$((YEAR % 100))$mm$dd.srs.gz"
      grep -qx "$name" "$TMP/names_$mm.txt" || { echo "skip $name: not listed" >&2; continue; }
      url="$BASE/$YEAR/$mm/$name"
      curl_small --range 0-32767 --output "$TMP/head.bin" "$url"
      curl_small --range -8 --dump-header "$TMP/tail.hdr" --output "$TMP/tail.bin" "$url"
      result="$(python3 "$HELPER" probe --date "$YEAR-$mm-$dd" --head-bin "$TMP/head.bin" \
        --tail-bin "$TMP/tail.bin" --tail-headers "$TMP/tail.hdr")"
      if [ "${result%%$'\t'*}" = "OK" ]; then
        IFS=$'\t' read -r _ size lm crc isize records first <<< "$result"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t-\n' "$requested" "$YEAR-$mm-$dd" "$name" "$url" \
          "$size" "$lm" "$crc" "$isize" "$records" "$first" >> "$OUT.tmp"
        echo "selected $requested -> $name records=$records size=$size first=$first" >&2
        chosen=1
        break
      fi
      echo "skip $name: $result" >&2
    done
    [ -n "$chosen" ] || { echo "FATAL: no acceptable file for $requested" >&2; exit 1; }
  done
done
mv "$OUT.tmp" "$OUT"
echo "wrote $OUT ($(($(wc -l < "$OUT") - 1)) days)" >&2
