#!/usr/bin/env bash
# Optional, documentation-only: re-derive sources.tsv from the live archive.
# Not part of the acceptance path (download.sh never calls it). Fetches the
# 65,536-byte archive tail and a 160 KB prefix of each band candidate (about
# 4 MB in total), applies the selection rule, and diffs against sources.tsv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="usgs_grandbay_klein3900_sidescan_xtf_u16"
WORK="${DISCOVER_DIR:-$DATA_ROOT/discover/$DATASET_ID}"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
HELPER="$RECIPE_DIR/scripts/xtf_sidescan.py"
ARCHIVE_URL="https://coastal.er.usgs.gov/data-release/doi-P9374DKQ/data/2015-315-FA_xtf.zip"
ARCHIVE_BYTES=9843630446
PREFIX_BYTES=160000
UA="openzl-public-datasets-usgs-grandbay-sidescan/1.0"

mkdir -p "$WORK/prefix" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID work=$WORK"

curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 300 \
  --max-filesize 70000 --user-agent "$UA" --range "$((ARCHIVE_BYTES - 65536))-$((ARCHIVE_BYTES - 1))" \
  --dump-header "$WORK/tail.headers" --output "$WORK/tail.bin" "$ARCHIVE_URL"
python3 "$HELPER" list-band "$WORK/tail.bin" "$WORK/tail.headers" > "$WORK/band.tsv"
echo "band candidates: $(wc -l < "$WORK/band.tsv")"

while IFS=$'\t' read -r -u 3 member lho _end csz _usz _crc _pings; do
  [ -s "$WORK/prefix/$member" ] && continue
  stop=$((lho + (csz < PREFIX_BYTES ? csz : PREFIX_BYTES) + 200))
  curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 120 \
    --max-filesize $((PREFIX_BYTES + 1000)) --user-agent "$UA" --range "$lho-$stop" \
    --output "$WORK/prefix/$member" "$ARCHIVE_URL"
done 3< "$WORK/band.tsv"

python3 "$HELPER" discover "$WORK/band.tsv" "$WORK/prefix" "$WORK/sources.tsv"
if diff -u "$RECIPE_DIR/sources.tsv" "$WORK/sources.tsv"; then
  echo "discover: live archive reproduces the pinned sources.tsv"
else
  echo "discover: live selection differs from the pinned sources.tsv" >&2
  exit 1
fi
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
