#!/usr/bin/env bash
# Documents how plan.tsv was resolved (run once at authoring time, 2026-10-08).
# Not part of download/build/verify. Writes only to a scratch directory.
set -euo pipefail
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-/tmp/autocollect/earthscope_pb_borehole_strain_counts_i32/discover}"
BASE="https://service.earthscope.org/fdsnws"
mkdir -p "$OUT"
curl -fsSL --max-time 120 -o "$OUT/ls_channels.txt" \
  "$BASE/station/1/query?net=PB&cha=LS?&level=channel&format=text"
python3 -I "$RECIPE_DIR/scripts/discover.py" probe-body --inventory "$OUT/ls_channels.txt" --out "$OUT/probe_post.txt"
# one large POST times out at the gateway (HTTP 504); send 120-line chunks
rm -f "$OUT"/probe_chunk_* "$OUT/probe.mseed"
split -l 120 -d -a 3 "$OUT/probe_post.txt" "$OUT/probe_chunk_"
for chunk in "$OUT"/probe_chunk_*; do
  curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors --max-time 600 \
    --data-binary @"$chunk" -o "$chunk.mseed" "$BASE/dataselect/1/query"
  [ -f "$chunk.mseed" ] && cat "$chunk.mseed" >> "$OUT/probe.mseed"
done
python3 -I "$RECIPE_DIR/scripts/discover.py" select --inventory "$OUT/ls_channels.txt" \
  --probe "$OUT/probe.mseed" --out "$OUT/plan.tsv"
echo "wrote $OUT/plan.tsv (copy to $RECIPE_DIR/plan.tsv to re-pin)"
