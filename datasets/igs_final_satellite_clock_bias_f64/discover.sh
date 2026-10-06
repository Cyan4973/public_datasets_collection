#!/usr/bin/env bash
# Resolve the pinned source list (sources.tsv) for igs_final_satellite_clock_bias_f64.
#
# For every 2024 day-of-year 001..182 this script computes the GPS week
# (2024-001 is GPS week 2295, day 1), reads the BKG GDC week-directory listing,
# requires exactly one IGS0OPSFIN_2024DDD0000_01D_30S_CLK.CLK.gz entry, and
# records the HTTP HEAD Content-Length, Last-Modified and ETag. BKG publishes no
# checksum files next to the products, so the sha256 column is left empty here
# and filled from the first validated download (see README.md).
#
# Metadata only: directory listings and HEAD requests, no product bytes.
# Usage: bash discover.sh [output.tsv]   (default: stdout)
set -euo pipefail

BASE="https://igs.bkg.bund.de/root_ftp/IGS/products"
UA="openzl-public-datasets-igs-clk-discover/1.0"
OUT="${1:-/dev/stdout}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf 'doy\tgps_week\tfilename\tsize_bytes\tlast_modified\tetag\tsha256\turl\n' > "$TMP/sources.tsv"
for doy in $(seq 1 182); do
  ddd="$(printf '%03d' "$doy")"
  # 2023-12-31 (2024 day 0) is the Sunday that starts GPS week 2295.
  week=$((2295 + doy / 7))
  listing="$TMP/week_$week.html"
  if [ ! -s "$listing" ]; then
    curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
      --max-time 120 --user-agent "$UA" --output "$listing" "$BASE/$week/"
  fi
  name="IGS0OPSFIN_2024${ddd}0000_01D_30S_CLK.CLK.gz"
  hits="$(grep -c "href=\"$name\"" "$listing" || true)"
  if [ "$hits" != "1" ]; then
    echo "expected one listing entry for $name in week $week, found $hits" >&2
    exit 1
  fi
  url="$BASE/$week/$name"
  headers="$(curl --fail --silent --show-error --location --head --retry 5 \
    --retry-delay 3 --max-time 60 --user-agent "$UA" "$url" | tr -d '\r')"
  final="$(printf '%s\n' "$headers" | awk 'BEGIN{b=""} /^HTTP\//{b=""} {b=b $0 "\n"} END{printf "%s", b}')"
  size="$(printf '%s' "$final" | awk -F': ' 'tolower($1)=="content-length"{print $2}' | tail -1)"
  modified="$(printf '%s' "$final" | awk -F': ' 'tolower($1)=="last-modified"{print $2}' | tail -1)"
  etag="$(printf '%s' "$final" | awk -F': ' 'tolower($1)=="etag"{print $2}' | tail -1 | tr -d '"')"
  case "$size" in
    ''|*[!0-9]*) echo "no Content-Length for $url" >&2; exit 1 ;;
  esac
  printf '%s\t%s\t%s\t%s\t%s\t%s\t\t%s\n' "$ddd" "$week" "$name" "$size" "$modified" "$etag" "$url" \
    >> "$TMP/sources.tsv"
done
cat "$TMP/sources.tsv" > "$OUT"
