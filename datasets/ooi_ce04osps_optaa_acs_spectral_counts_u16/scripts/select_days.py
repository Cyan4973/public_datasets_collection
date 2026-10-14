#!/usr/bin/env python3
"""Select the pinned AC-S day files from saved OOI directory listings.

Usage: select_days.py LISTING_HTML... > selection.tsv

Eligible file: OPTAAD105_10.33.10.202_2101_2019MMDDT07(20|21)_UTC.dat with a
listing date equal to the file date, listing time 21:4x (the port agent
closes complete files at 21:43-21:44 UTC), listed size 23M..25M, and date in
2019-01-01 .. 2019-06-13 (AC-S serial 128, 84 wavelengths; after the
2019-06-14 .. 2019-06-25 gap a different unit, serial 221 with 88
wavelengths, is installed). Targets are 2019-01-01 + 5k days; a target that is
not eligible is replaced by the next eligible day that is not already chosen.
Prints day, filename, listing month directory.
"""
import re
import sys
from datetime import date, timedelta

ROW = re.compile(
    r'href="(OPTAAD105_10\.33\.10\.202_2101_(2019)(\d\d)(\d\d)T07(?:20|21)_UTC\.dat)">[^<]*</a>\s+'
    r'(\d{4}-\d\d-\d\d) (\d\d):(\d\d)\s+([0-9.]+)([KMG])'
)
FIRST = date(2019, 1, 1)
LAST = date(2019, 6, 13)
STEP = 5


def main() -> int:
    eligible = {}
    for path in sys.argv[1:]:
        text = open(path, encoding="utf-8", errors="replace").read()
        for m in ROW.finditer(text):
            fname, y, mo, d, ldate, hh, mm, size, unit = m.groups()
            day = date(int(y), int(mo), int(d))
            if not (FIRST <= day <= LAST):
                continue
            if ldate != day.isoformat() or hh != "21" or not mm.startswith("4"):
                continue
            if unit != "M" or not (23 <= float(size) <= 25):
                continue
            eligible[day] = fname
    chosen = []
    t = FIRST
    while t <= LAST:
        c = t
        while c <= LAST and (c not in eligible or c in chosen):
            c += timedelta(days=1)
        if c <= LAST and c not in chosen:
            chosen.append(c)
        t += timedelta(days=STEP)
    print(f"eligible={len(eligible)} chosen={len(chosen)}", file=sys.stderr)
    for c in chosen:
        print(f"{c.strftime('%Y%m%d')}\t{eligible[c]}\t{c.strftime('%Y/%m')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
