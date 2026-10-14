#!/usr/bin/env bash
# Documentation/reproduction of how members.tsv and excluded_gain10000.tsv were
# derived (2026-10-14). Not part of the download/build/verify path. Fetches
# raw_data.csv, the zip central directory, and a ~4 KB prefix of each
# candidate member (enough to inflate the 512-byte PNT header) into
# $DATA_DIR/discovery/<id>/, then writes regenerated TSVs there for diffing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="slf_envidat_wfj_snowmicropen_force_i16"
OUT="$DATA_ROOT/discovery/$DATASET_ID"
BASE_URL="https://zhc-c.s3.cloud.switch.ch/envidat-doi/10.16904_envidat.641/data"
ZIP_SIZE=3134603173
CD_OFFSET=3132965021
CURL=(curl --globoff --fail --silent --show-error --location --retry 5 --retry-delay 3 --max-time 120)

mkdir -p "$OUT/prefixes"
"${CURL[@]}" -o "$OUT/raw_data.csv" "$BASE_URL/raw_data.csv"
"${CURL[@]}" --range "$CD_OFFSET-$((ZIP_SIZE - 1))" -o "$OUT/cd.bin" "$BASE_URL/raw_data.zip"
python3 -I "$RECIPE_DIR/scripts/discover_select.py" candidates "$OUT/cd.bin" "$OUT/raw_data.csv" "$OUT/candidates.tsv"
while IFS=$'\t' read -r name _date _q offset _nl _cs _us _crc; do
  target="$OUT/prefixes/${name//\//__}.prefix"
  [[ -s "$target" ]] || "${CURL[@]}" --range "$offset-$((offset + 4095))" -o "$target" "$BASE_URL/raw_data.zip"
done < "$OUT/candidates.tsv"
python3 -I "$RECIPE_DIR/scripts/discover_select.py" select "$OUT/candidates.tsv" "$OUT/prefixes" \
  "$OUT/members.tsv" "$OUT/excluded_gain10000.tsv"
diff -q "$OUT/members.tsv" "$RECIPE_DIR/members.tsv" && diff -q "$OUT/excluded_gain10000.tsv" "$RECIPE_DIR/excluded_gain10000.tsv" \
  && echo "discovery reproduces the pinned TSVs"
