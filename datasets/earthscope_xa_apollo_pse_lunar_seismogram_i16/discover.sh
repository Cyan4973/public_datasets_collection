#!/usr/bin/env bash
# Documentation of how plan.tsv was resolved (run once on 2026-10-09; build and
# verify never run this). Writes scratch files to $WORK (default a mktemp dir)
# and plan.tsv into $PLAN_OUT (default $WORK/plan.tsv; copy it into the recipe
# deliberately).
set -euo pipefail
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${EARTHSCOPE_FDSNWS_BASE:-https://service.earthscope.org/fdsnws}"
WORK="${WORK:-$(mktemp -d /tmp/xa_apollo_discover.XXXXXX)}"
PLAN_OUT="${PLAN_OUT:-$WORK/plan.tsv}"
mkdir -p "$WORK"
UA="openzl-public-datasets-collection/1.0 (earthscope_xa_apollo_pse_lunar_seismogram_i16 discover)"

curl --fail --silent --show-error --location --max-time 120 --user-agent "$UA" \
  --output "$WORK/xa_channels.txt" \
  "$BASE/station/1/query?net=XA&starttime=1969-07-01&endtime=1977-12-31&level=channel&format=text"
python3 -I "$RECIPE_DIR/scripts/discover.py" probe-body --inventory "$WORK/xa_channels.txt" --out "$WORK/probe_body.txt"
# one big POST times out at the gateway (HTTP 504); send 48 windows per POST
rm -f "$WORK"/probe_chunk_* "$WORK/probe.mseed"
tail -n +2 "$WORK/probe_body.txt" | split -l 48 - "$WORK/probe_chunk_"
for c in "$WORK"/probe_chunk_*; do
  { echo "nodata=404"; cat "$c"; } > "$c.body"
  code="$(curl --silent --show-error --location --max-time 600 --retry 5 --retry-delay 10 --retry-all-errors \
    --user-agent "$UA" --data-binary @"$c.body" --output "$c.mseed" --write-out '%{http_code}' "$BASE/dataselect/1/query")"
  case "$code" in
    200) cat "$c.mseed" >> "$WORK/probe.mseed" ;;
    404|204) echo "no data for $(basename "$c")" ;;
    *) echo "FATAL: HTTP $code for $(basename "$c")" >&2; exit 1 ;;
  esac
done
echo "probe bytes: $(wc -c < "$WORK/probe.mseed")"
python3 -I "$RECIPE_DIR/scripts/discover.py" select --inventory "$WORK/xa_channels.txt" \
  --probe "$WORK/probe.mseed" --out "$PLAN_OUT"
echo "plan written to $PLAN_OUT"
