#!/usr/bin/env bash
# Regenerates sources.tsv from the twelve NCEI 2022 pg2 (DSI 6406) directory
# listings. Metadata only (HTML listings, ~150 KB each); never downloads data
# files. The committed sources.tsv is what download.sh uses; rerun this only to
# re-pin after NCEI republishes files (sizes or timestamps change).
#
# Selection rule (applied identically to every station): a station-month is
# kept when its listed size is at least 80% of a complete month of 113-byte
# records (days x 1440 x 113 bytes). Shorter files contain long outages and are
# skipped rather than kept as short samples.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YEAR=2022
BASE="https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg2/access/$YEAR"
STATIONS="KPHX KIPL KMAF KABQ KLAS KELY KGJT KSLC KCPR KHLN KBIL KRNO KSEA KPDX KSFO KSAN KMFR KABR KMOT KINL KMSP KDDC KOKC KORD KDTW KIND KSTL KIAH KMSY KMEM KJAX KMIA KEYW KCHS KRDU KBOS KBTV KPWM PAFA PANC PAJN PATO PHNL TJSJ"
MIN_COVERAGE=0.80
TMP="$(mktemp -d /tmp/asos_pg2_discover.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
  curl -fsS --retry 5 --retry-delay 3 --max-time 180 -o "$TMP/list_$m.html" "$BASE/$m/"
done

python3 -I - "$TMP" "$BASE" "$RECIPE_DIR/sources.tsv" "$YEAR" "$MIN_COVERAGE" $STATIONS <<'PY'
import calendar
import re
import sys
from pathlib import Path

tmp, base, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
year, min_cov = int(sys.argv[4]), float(sys.argv[5])
stations = sys.argv[6:]
row_re = re.compile(
    r'<a href="(asos-1min-pg2-([A-Z0-9]{4})-' + str(year) + r'(\d\d)\.dat)">[^<]*</a></td>\s*'
    r'<td[^>]*>([^<]*)</td>\s*<td[^>]*>(\d+)</td>'
)
found = {}
for month in range(1, 13):
    text = (tmp / f"list_{month:02d}.html").read_text(encoding="utf-8")
    for name, station, mm, modified, size in row_re.findall(text):
        if int(mm) != month:
            raise SystemExit(f"listing month mismatch for {name}")
        found[(station, month)] = (name, int(size), modified.strip().replace(" ", "T"))
lines = ["station\tmonth\tfilename\tsize_bytes\tlast_modified\tcoverage\turl"]
skipped = []
for station in sorted(stations):
    for month in range(1, 13):
        full = calendar.monthrange(year, month)[1] * 1440 * 113
        if (station, month) not in found:
            skipped.append(f"{station}-{month:02d}:absent")
            continue
        name, size, modified = found[(station, month)]
        coverage = size / full
        if coverage < min_cov:
            skipped.append(f"{station}-{month:02d}:{coverage:.3f}")
            continue
        lines.append(f"{station}\t{year}-{month:02d}\t{name}\t{size}\t{modified}\t{coverage:.4f}\t{base}/{month:02d}/{name}")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
total = sum(int(line.split("\t")[3]) for line in lines[1:])
kept_stations = sorted({line.split("\t")[0] for line in lines[1:]})
print(f"wrote {out} stations={len(kept_stations)} station_months={len(lines) - 1} total_bytes={total}")
print("skipped " + " ".join(skipped))
PY
