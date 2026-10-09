#!/usr/bin/env bash
# Documentation of how blocks.tsv was resolved (metadata only: header, root
# directory, and the leaf directories for the fixed city blocks). Not part of
# the download/build/verify path. Usage: bash discover.sh SCRATCH_DIR > blocks.tsv
set -euo pipefail
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRATCH="${1:?scratch dir}"
URL="https://build.protomaps.com/20250120.pmtiles"
mkdir -p "$SCRATCH/leaves"
curl -sSfL --max-time 60 -r 0-16383 -o "$SCRATCH/head16k.bin" "$URL"
python3 -I "$RECIPE_DIR/scripts/discover.py" leaves "$SCRATCH/head16k.bin" "$RECIPE_DIR/cities.tsv" |
while IFS=$'\t' read -r rel len abs; do
  out="$SCRATCH/leaves/leaf_${rel}.gz"
  [[ -s "$out" && "$(stat -c %s "$out")" == "$len" ]] && continue
  curl -sSfL --max-time 120 -r "${abs}-$((abs + len - 1))" -o "$out" "$URL"
done
python3 -I "$RECIPE_DIR/scripts/discover.py" blocks "$SCRATCH/head16k.bin" "$RECIPE_DIR/cities.tsv" "$SCRATCH/leaves"
