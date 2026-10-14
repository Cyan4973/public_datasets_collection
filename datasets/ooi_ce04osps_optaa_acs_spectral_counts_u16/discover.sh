#!/usr/bin/env bash
# Documentation of how sources.tsv was resolved (run 2026-10-14). Metadata only:
# fetches six directory listings and HEADs the selected files; no payloads.
# Usage: bash discover.sh > sources.tsv
set -euo pipefail
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="https://rawdata.oceanobservatories.org/files/CE04OSPS/SF01B/OPTAAD105"
UA="openzl-public-datasets-ooi-optaa-discover/1.0"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for m in 01 02 03 04 05 06; do
  curl --silent --show-error --fail --max-time 60 --retry 3 --user-agent "$UA" \
    --output "$TMP/list_$m.html" "$BASE/2019/$m/"
done
python3 -I "$RECIPE_DIR/scripts/select_days.py" "$TMP"/list_*.html > "$TMP/selection.tsv"
printf 'day\tfilename\tsize_bytes\tetag\tlast_modified\turl\n'
while IFS=$'\t' read -r day filename monthdir; do
  url="$BASE/$monthdir/$filename"
  headers="$(curl --silent --show-error --fail --head --max-time 60 --retry 3 --user-agent "$UA" "$url" | tr -d '\r')"
  size="$(awk -F': ' 'tolower($1)=="content-length"{print $2}' <<<"$headers" | tail -1)"
  etag="$(awk -F': ' 'tolower($1)=="etag"{gsub(/"/,"",$2); print $2}' <<<"$headers" | tail -1)"
  lm="$(awk -F': ' 'tolower($1)=="last-modified"{print $2}' <<<"$headers" | tail -1)"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$day" "$filename" "$size" "$etag" "$lm" "$url"
done < "$TMP/selection.tsv"
