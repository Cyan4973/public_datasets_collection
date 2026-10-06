#!/usr/bin/env python3
"""Deterministic day selection for gfz_gracefo_fgm_acal_bnec_f64.

Used by discover.sh only (download/build never re-select; they read the
pinned sources.tsv).  Input: the two Apache directory listings of
https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201/GF{1,2}/ACAL_CORR/.

Rule (documented in README.md):
  * candidate files: version 0201, complete UTC days only (first entry
    T000000, last entry T235959, same date), months 2024-12, 2025-02 and
    2026-05 excluded (reprocessed to v0202 / v0201 withdrawn per README.txt);
  * slot dates: 2018-06-15 + 45*k days for k = 0, 1, ... while <= 2026-08-31;
  * preferred satellite alternates by slot: GF1 for even k, GF2 for odd k;
    if the preferred satellite has no candidate file on the slot date the
    other satellite's file for that date is used; if neither has one the slot
    is skipped.  At most one file per date, so the GF1/GF2 tandem pair (same
    orbit, ~30 s apart) never contributes two near-copies of the same day.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

NAME_RE = re.compile(
    r"^(GF[12])_OPER_FGM_ACAL_CORR_(\d{8})T(\d{6})_(\d{8})T(\d{6})_(\d{4})\.cdf$"
)
HREF_RE = re.compile(r'href="(GF[12]_OPER_FGM_ACAL_CORR_[^"/]+\.cdf)"')
VERSION = "0201"
EXCLUDED_MONTHS = {"202412", "202502", "202605"}
FIRST_SLOT = dt.date(2018, 6, 15)
LAST_DAY = dt.date(2026, 8, 31)
CADENCE_DAYS = 45


def candidates(listing: str, satellite: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in HREF_RE.findall(listing):
        match = NAME_RE.match(name)
        if not match:
            raise SystemExit(f"unexpected file name in listing: {name}")
        sat, day0, t0, day1, t1, version = match.groups()
        if sat != satellite:
            raise SystemExit(f"{name} listed under {satellite}")
        if version != VERSION or day0 != day1 or t0 != "000000" or t1 != "235959":
            continue
        if day0[:6] in EXCLUDED_MONTHS:
            continue
        if day0 in out:
            raise SystemExit(f"duplicate full-day file for {satellite} {day0}")
        out[day0] = name
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gf1-listing", type=Path, required=True)
    parser.add_argument("--gf2-listing", type=Path, required=True)
    args = parser.parse_args()
    files = {
        "GF1": candidates(args.gf1_listing.read_text(encoding="utf-8"), "GF1"),
        "GF2": candidates(args.gf2_listing.read_text(encoding="utf-8"), "GF2"),
    }
    print(f"# candidates GF1={len(files['GF1'])} GF2={len(files['GF2'])}", file=sys.stderr)
    k = 0
    selected = 0
    while True:
        day = FIRST_SLOT + dt.timedelta(days=CADENCE_DAYS * k)
        if day > LAST_DAY:
            break
        key = day.strftime("%Y%m%d")
        preferred = "GF1" if k % 2 == 0 else "GF2"
        other = "GF2" if preferred == "GF1" else "GF1"
        choice = None
        for sat in (preferred, other):
            if key in files[sat]:
                choice = sat
                break
        if choice is None:
            print(f"# slot {k} {key}: no complete v0201 file on either satellite; skipped", file=sys.stderr)
        else:
            note = "preferred" if choice == preferred else f"fallback_from_{preferred}"
            print(f"{k}\t{key}\t{choice}\t{note}\t{files[choice][key]}")
            selected += 1
        k += 1
    print(f"# slots={k} selected={selected}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
