#!/usr/bin/env bash
# Author-time discovery: documents how files.tsv was resolved.  Not part of the
# download/build path.  Fetches only small JSON metadata (segment list and one
# strain-file detail document per candidate slot) with curl.
#
#   bash staging/gwosc_o3b_h1_bulk_strain_f64/discover.sh [out_dir]
#
# Writes <out_dir>/files.tsv (default /tmp/autocollect/gwosc_o3b_h1_bulk_strain_f64/discover).
set -euo pipefail
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-/tmp/autocollect/gwosc_o3b_h1_bulk_strain_f64/discover}"
RUN_START=1256655618   # /api/v2/runs/O3b gps_start
RUN_END=1269363618     # /api/v2/runs/O3b gps_end
N=7
mkdir -p "$OUT/details"
CURL=(curl -fsSL --retry 5 --retry-delay 5 --max-time 120)

"${CURL[@]}" -o "$OUT/segments.json" \
  "https://gwosc.org/timeline/segments/json/O3b_4KHZ_R1/H1_DATA/$RUN_START/$((RUN_END - RUN_START))/"

python3 -I "$RECIPE_DIR/scripts/discover.py" candidates --segments "$OUT/segments.json" \
  --run-start "$RUN_START" --run-end "$RUN_END" --n "$N" > "$OUT/candidates.txt"

while read -r gps; do
  f="$OUT/details/H1-$gps-4kHz.json"
  [ -s "$f" ] || "${CURL[@]}" -o "$f" "https://gwosc.org/api/v2/strain-files/H1-$gps-4kHz?format=json" || rm -f "$f"
done < "$OUT/candidates.txt"

python3 -I "$RECIPE_DIR/scripts/discover.py" finalize --segments "$OUT/segments.json" \
  --run-start "$RUN_START" --run-end "$RUN_END" --n "$N" --details-dir "$OUT/details" --out "$OUT/files.tsv"
