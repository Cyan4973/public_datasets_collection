#!/usr/bin/env bash
# Metadata-only discovery that documents how selection.tsv was resolved.
#
# It lists the seven pinned day prefixes with paginated S3 ListObjectsV2
# (continuation-token), range-GETs the first 2,048 and last 4,096 bytes of
# every object to read PROVIDER, UNIQUE_ID and the first/last TIME/LON/LAT,
# and regenerates selection.tsv with scripts/select_sources.py.
# download.sh does not call this script; it trusts the committed, hash-pinned
# selection.tsv. Re-running it later may differ if NCEI adds or removes
# objects in these prefixes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="noaa_dcdb_csb_vessel_track_lonlat_f64"
BUCKET="https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com"
PREFIX_ROOT="csb/csv/2024/06"
DAYS=(01 02 03 04 05 06 07)
DISC_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
OUTPUT="${SELECTION_OUTPUT:-$RECIPE_DIR/selection.tsv}"

mkdir -p "$DISC_DIR/listing" "$DISC_DIR/heads" "$DISC_DIR/tails" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID"

LISTING="$DISC_DIR/listing.tsv"
: > "$LISTING"
for day in "${DAYS[@]}"; do
  prefix="$PREFIX_ROOT/$day/"
  cursor=""
  page=0
  while :; do
    url="$BUCKET/?list-type=2&prefix=$prefix&max-keys=1000"
    [[ -z "$cursor" ]] || url="$url&continuation-token=$cursor"
    xml="$DISC_DIR/listing/day${day}_page${page}.xml"
    curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
      --max-time 120 --output "$xml" "$url"
    python3 "$RECIPE_DIR/scripts/select_sources.py" parse-listing "$xml" \
      --state "$DISC_DIR/listing/state" >> "$LISTING"
    truncated="$(sed -n 1p "$DISC_DIR/listing/state")"
    cursor="$(sed -n 2p "$DISC_DIR/listing/state")"
    page=$((page + 1))
    [[ "$truncated" == "true" ]] || break
  done
  echo "listed prefix=$prefix pages=$page"
done
echo "listed objects=$(wc -l < "$LISTING")"

probe() {
  local key="$1" name
  name="$(basename "$key")"
  [[ -s "$DISC_DIR/heads/$name" ]] || curl --fail --silent --show-error --retry 5 \
    --max-time 60 --range 0-2047 --output "$DISC_DIR/heads/$name" "$BUCKET/$key"
  [[ -s "$DISC_DIR/tails/$name" ]] || curl --fail --silent --show-error --retry 5 \
    --max-time 60 --range -4096 --output "$DISC_DIR/tails/$name" "$BUCKET/$key"
}
export -f probe
export BUCKET DISC_DIR
cut -f1 "$LISTING" | xargs -P 16 -I{} bash -c 'probe "$@"' _ {}
echo "probed heads=$(ls "$DISC_DIR/heads" | wc -l) tails=$(ls "$DISC_DIR/tails" | wc -l)"

python3 "$RECIPE_DIR/scripts/select_sources.py" select \
  --listing "$LISTING" --heads "$DISC_DIR/heads" --tails "$DISC_DIR/tails" \
  --output "$OUTPUT"
echo "selection_sha256=$(sha256sum "$OUTPUT" | awk '{print $1}')"
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
