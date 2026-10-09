#!/usr/bin/env python3
"""Deterministic day selection for gracefo_l1b_ach1b_transplant_accelerometer_f64.

Used by discover.sh only. download.sh and build.sh never re-select; they read
the pinned sources.tsv.

Input: the Apache directory listings of
https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/<YYYY>/ for
2023, 2024, 2025 and 2026.

Rule (documented in README.md):
  * candidates: every daily ``gracefo_1B_<YYYY-MM-DD>_RL04.ascii.ACX2.tgz``
    dated 2023-01-01..2026-06-30, inclusive. ACX2 is the accelerometer tarball
    line in which every ACH1B day is produced from the ACH1A L1A input with
    one software build. The older ``ACX`` tarballs mix several input lineages
    (ACC1A, ACH1A, ASO1A, AFO1A, ACT1A) and are not used.
  * sort the candidates by date and keep every STRIDE-th one, starting with the
    first (index 0, 12, 24, ...).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

HREF_RE = re.compile(r'href="(gracefo_1B_(\d{4}-\d{2}-\d{2})_RL04\.ascii\.ACX2\.tgz)"')
FIRST_DAY = dt.date(2023, 1, 1)
LAST_DAY = dt.date(2026, 6, 30)
STRIDE = 12


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("listings", nargs="+", type=Path)
    args = parser.parse_args()
    found: dict[dt.date, str] = {}
    for path in args.listings:
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, day in HREF_RE.findall(text):
            date = dt.date.fromisoformat(day)
            if not (FIRST_DAY <= date <= LAST_DAY):
                continue
            if date in found and found[date] != name:
                raise SystemExit(f"duplicate ACX2 entry for {day}")
            found[date] = name
    days = sorted(found)
    if not days:
        raise SystemExit("no ACX2 candidates found")
    picked = days[::STRIDE]
    print(f"candidates={len(days)} first={days[0]} last={days[-1]} stride={STRIDE} picked={len(picked)}",
          file=sys.stderr)
    for index, date in enumerate(picked):
        print(f"{index * STRIDE}\t{date.isoformat()}\t{found[date]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
