#!/usr/bin/env bash
# Regenerates sources.tsv from the twelve NCEI 2024 pg1 directory listings.
# Metadata only (HTML listings, ~100 KB each); never downloads data files.
# The committed sources.tsv is what download.sh uses; rerun this only to
# re-pin after NCEI republishes files (sizes or timestamps change).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/access/2024"
STATIONS="KABQ KABR KBIS KBOS KBTV KCLE KCPR KDDC KDEN KDSM KFAR KGLD KGRI KHON KIAH KJAX KJFK KLBF KMIA KMKE KMOT KMSY KORD KPHL KPWM KRAP KSEA KSLC KSTL KSUX"
TMP="$(mktemp -d /tmp/asos_pg1_discover.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
  curl -fsS --retry 5 --retry-delay 3 --max-time 180 -o "$TMP/list_$m.html" "$BASE/$m/"
done

python3 -I - "$TMP" "$BASE" "$RECIPE_DIR/sources.tsv" $STATIONS <<'PY'
import re
import sys
from pathlib import Path

tmp, base, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
stations = sys.argv[4:]
row_re = re.compile(
    r'<a href="(asos-1min-pg1-([A-Z0-9]{4})-2024(\d\d)\.dat)">[^<]*</a></td>\s*'
    r'<td[^>]*>([^<]*)</td>\s*<td[^>]*>(\d+)</td>'
)
found = {}
for month in range(1, 13):
    text = (tmp / f"list_{month:02d}.html").read_text(encoding="utf-8")
    for name, station, mm, modified, size in row_re.findall(text):
        if int(mm) != month:
            raise SystemExit(f"listing month mismatch for {name}")
        found[(station, month)] = (name, int(size), modified.strip().replace(" ", "T"))
lines = ["station\tmonth\tfilename\tsize_bytes\tlast_modified\turl"]
for station in sorted(stations):
    for month in range(1, 13):
        if (station, month) not in found:
            raise SystemExit(f"missing station-month {station} 2024-{month:02d}")
        name, size, modified = found[(station, month)]
        lines.append(f"{station}\t2024-{month:02d}\t{name}\t{size}\t{modified}\t{base}/{month:02d}/{name}")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
total = sum(int(line.split("\t")[3]) for line in lines[1:])
print(f"wrote {out} station_months={len(lines) - 1} total_bytes={total}")
PY
