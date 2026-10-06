#!/usr/bin/env bash
# Authoring-time discovery (metadata only): regenerate sources.tsv, the pinned
# list of JPL COSMIC-1 v2.6 L1b occultation files this recipe downloads.
#
# For every month 2007-01 .. 2016-12: list the month's day prefixes, choose
# the available day nearest the 15th (ties -> earlier day), list that day's
# keys completely (S3 ListObjectsV2 pages of 1000 keys, continuation tokens),
# sort the keys and take 20 evenly spaced ones (index floor((2i+1)n/40)).
# Sizes and single-part MD5 ETags are pinned with each key.
#
# download.sh does NOT run this; it fetches exactly the keys in sources.tsv
# and refuses a list whose SHA-256 differs from the one pinned in
# scripts/gnssro.py.  Listing XML goes to DISCOVERY_DIR (default under /tmp).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="jpl_gnssro_cosmic1_l1b_excess_phase_f64"
DISCOVERY_DIR="${DISCOVERY_DIR:-${TMPDIR:-/tmp}/${DATASET_ID}_discovery}"
OUT="${SOURCES_OUT:-$RECIPE_DIR/sources.tsv}"
BASE_URL="https://gnss-ro-data.s3.amazonaws.com"
ROOT_PREFIX="contributed/v2.0/gnssro_cosmic1_jpl_l1b"
UA="openzl-public-datasets-gnssro-cosmic1/1.0"
PY="$RECIPE_DIR/scripts/gnssro.py"

mkdir -p "$DISCOVERY_DIR"
echo "[$(date -Is)] discovery start dir=$DISCOVERY_DIR"

list() {  # list <out> <prefix> [delimiter] [cursor]
  local out="$1" prefix="$2" delimiter="${3:-}" cursor="${4:-}"
  if [ -s "$out" ]; then
    return
  fi
  local args=(--get --data-urlencode "list-type=2" --data-urlencode "prefix=$prefix")
  if [ -n "$delimiter" ]; then
    args+=(--data-urlencode "delimiter=$delimiter")
  fi
  if [ -n "$cursor" ]; then
    args+=(--data-urlencode "continuation-token=$cursor")
  fi
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors --max-time 300 \
    --user-agent "$UA" --output "$out.part" "${args[@]}" "$BASE_URL/"
  mv "$out.part" "$out"
}

: > "$DISCOVERY_DIR/chosen_days.tsv.part"
for year in $(seq 2007 2016); do
  for mon in 01 02 03 04 05 06 07 08 09 10 11 12; do
    month="$year-$mon"
    list "$DISCOVERY_DIR/month_$month.xml" "$ROOT_PREFIX/$year/$mon/" "/"
    day="$(python3 "$PY" pick-day --month "$month" --listing "$DISCOVERY_DIR/month_$month.xml")"
    printf '%s\t%s\n' "$month" "$day" >> "$DISCOVERY_DIR/chosen_days.tsv.part"
    if [ -z "$day" ]; then
      echo "month=$month no_days"
      continue
    fi
    prefix="$ROOT_PREFIX/$year/$mon/$day/"
    page=1
    cursor=""
    while :; do
      out="$DISCOVERY_DIR/day_$month-$day.p$(printf '%02d' "$page").xml"
      list "$out" "$prefix" "" "$cursor"
      cursor="$(python3 "$PY" next-token --prefix "$prefix" --listing "$out")"
      if [ -z "$cursor" ]; then
        break
      fi
      page=$((page + 1))
    done
    echo "month=$month day=$day pages=$page"
  done
done
mv "$DISCOVERY_DIR/chosen_days.tsv.part" "$DISCOVERY_DIR/chosen_days.tsv"

python3 "$PY" select --listings "$DISCOVERY_DIR" --out "$OUT"
echo "[$(date -Is)] discovery done out=$OUT"
