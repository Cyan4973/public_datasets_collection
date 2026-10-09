#!/usr/bin/env bash
# Re-derive sources.tsv: TAP query for all Walz lunar plates, header-range probes, selection.
# Not run by download.sh; documents how the pins were resolved (2026-10-09).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${DISCOVER_DIR:-/tmp/autocollect/gavo_hdap_walz_photographic_plate_scans_u16/discover}"
TAP="https://dc.g-vo.org/tap/sync"
QUERY="SELECT accref,accsize,dateObs,plateID,object,instId,exposure,startTime,endTime FROM lsw.plates WHERE instId LIKE '%Walz%' AND object LIKE 'Moon%' ORDER BY dateObs"
mkdir -p "$WORK/headers"

curl -fsS --retry 5 --retry-delay 5 --max-time 300 "$TAP" \
  --data-urlencode "REQUEST=doQuery" --data-urlencode "LANG=ADQL" \
  --data-urlencode "FORMAT=csv" --data-urlencode "QUERY=$QUERY" -o "$WORK/walz_moon.csv"

python3 -I -B - "$WORK/walz_moon.csv" <<'PY' | while read -r url; do
import csv, sys
for row in csv.DictReader(open(sys.argv[1], encoding="utf-8")):
    print(row["accref"])
PY
  plate="$(basename "$url" .fits)"
  curl -fsS --retry 5 --retry-delay 5 --max-time 120 -r 0-28799 \
    -D "$WORK/headers/$plate.http" -o "$WORK/headers/$plate.fits" "$url"
done

python3 -I -B "$RECIPE_DIR/scripts/discover.py" --work "$WORK" --out "$WORK/sources.tsv"
if cmp -s <(grep -v '^#' "$WORK/sources.tsv") <(grep -v '^#' "$RECIPE_DIR/sources.tsv"); then
  echo "sources.tsv unchanged"
else
  echo "sources.tsv differs from the pinned copy: $WORK/sources.tsv"
fi
