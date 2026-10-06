#!/usr/bin/env bash
# Metadata-only discovery: fetch the Zenodo record JSON and the last 128 KiB
# (end-of-central-directory + central directory) of each Data_ID_07..21 zip,
# then re-derive selection.tsv and compare it with the committed one.
# Usage: bash discover.sh [OUT_DIR]   (default /tmp/isea_hss_discover)
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-/tmp/isea_hss_discover}"
RECORD_ID=12091223
UA="openzl-public-datasets-isea-hss-voltage/1.0"
TAIL_BYTES=131072
mkdir -p "$OUT_DIR"

curl --fail --silent --show-error --location --retry 6 --retry-delay 10 --retry-all-errors \
  --max-time 120 --user-agent "$UA" --output "$OUT_DIR/record.json" \
  "https://zenodo.org/api/records/$RECORD_ID"

for sid in 07 08 09 10 11 12 14 15 16 18 19 20 21; do
  key="Data_ID_$sid.zip"
  size="$(python3 -c 'import json,sys; print(next(f["size"] for f in json.load(open(sys.argv[1]))["files"] if f["key"]==sys.argv[2]))' "$OUT_DIR/record.json" "$key")"
  curl --fail --silent --show-error --location --retry 6 --retry-delay 10 --retry-all-errors \
    --max-time 120 --user-agent "$UA" --range "$((size - TAIL_BYTES))-$((size - 1))" \
    --output "$OUT_DIR/$key.tail" "https://zenodo.org/api/records/$RECORD_ID/files/$key/content"
  sleep 2
done

python3 "$RECIPE_DIR/scripts/discover_members.py" "$OUT_DIR" --check "$RECIPE_DIR/selection.tsv"
