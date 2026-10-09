#!/usr/bin/env python3
"""Select and pin the HDAP Walz lunar plates (run by discover.sh, not by download.sh).

Inputs (fetched by discover.sh with curl):
  <work>/walz_moon.csv          TAP result: every lsw.plates row with instId LIKE '%Walz%'
                                AND object LIKE 'Moon%', ordered by dateObs
  <work>/headers/<plate>.fits   first 28,800 bytes of every listed plate (Range GET)
  <work>/headers/<plate>.http   response headers of that Range GET

Selection rule (deterministic):
  1. eligible = Walz lunar plates with accsize <= 62,000,000 bytes whose primary header passes
     the regime (SIMPLE, BITPIX 16, NAXIS 2, BZERO 32768, BSCALE 1, no BLANK, TELESCOP
     '72cm Walz Reflektor', OBJECT 'Moon*', file size == header + data + padding, i.e. no
     extension HDUs).  43 of the 46 lunar plates qualify (D59, D60, D61 are 75-147 MB).
  2. group by observing season of startTime: S1 1906-12..1907-02, S2 1907-03..04, S3 1909,
     S4 1918, S5 1920, S6 1924.
  3. keep every plate of the sparse seasons S1, S4, S5, S6; take 7 of S2 and 8 of S3 at evenly
     spaced date ranks (index round(i*(n-1)/(k-1))).  This keeps the primary total < 900 MB.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitsplate  # noqa: E402

MAX_ACCSIZE = 62_000_000
PICK = {"S2": 7, "S3": 8}
COLUMNS = [
    "plate_id", "url", "size_bytes", "last_modified", "naxis1", "naxis2", "header_bytes",
    "header_sha256", "fits_date_obs", "tap_dateobs_mjd", "start_time", "season", "object",
]


def season(start_time: str) -> str:
    year, month = int(start_time[:4]), int(start_time[5:7])
    if year == 1906 or (year == 1907 and month < 3):
        return "S1"
    return {1907: "S2", 1909: "S3", 1918: "S4", 1920: "S5", 1924: "S6"}[year]


def even(items: list, k: int) -> list:
    n = len(items)
    if k >= n:
        return items
    return [items[round(i * (n - 1) / (k - 1))] for i in range(k)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    rows = list(csv.DictReader((args.work / "walz_moon.csv").open(encoding="utf-8")))
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if "Walz" not in row["instId"] or not row["object"].startswith("Moon"):
            raise SystemExit(f"unexpected TAP row {row['accref']}")
        plate = Path(row["accref"]).stem
        size = int(row["accsize"])
        if size > MAX_ACCSIZE:
            print(f"skip {plate}: accsize {size} > {MAX_ACCSIZE}")
            continue
        blob = (args.work / "headers" / f"{plate}.fits").read_bytes()
        http = (args.work / "headers" / f"{plate}.http").read_text(encoding="iso-8859-1")
        cr = re.search(r"^Content-Range:\s*bytes\s+0-\d+/(\d+)", http, re.I | re.M)
        lm = re.search(r"^Last-Modified:\s*(.+?)\s*$", http, re.I | re.M)
        if not cr or int(cr.group(1)) != size:
            raise SystemExit(f"{plate}: Content-Range total disagrees with accsize {size}")
        cards, header_bytes = fitsplate.parse_primary_header(blob)
        try:
            facts = fitsplate.check_regime(cards, header_bytes, size)
        except fitsplate.RegimeError as exc:
            print(f"skip {plate}: {exc}")
            continue
        entry = {
            "plate_id": plate,
            "url": row["accref"],
            "size_bytes": str(size),
            "last_modified": lm.group(1) if lm else "",
            "naxis1": str(facts["naxis1"]),
            "naxis2": str(facts["naxis2"]),
            "header_bytes": str(header_bytes),
            "header_sha256": fitsplate.header_sha256(blob, header_bytes),
            "fits_date_obs": facts["date_obs"],
            "tap_dateobs_mjd": row["dateObs"],
            "start_time": row["startTime"],
            "season": season(row["startTime"]),
            "object": row["object"],
        }
        groups.setdefault(entry["season"], []).append(entry)
    eligible = sum(len(v) for v in groups.values())
    selected = []
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda e: float(e["tap_dateobs_mjd"]))
        chosen = even(members, PICK[key]) if key in PICK else members
        print(f"season {key}: eligible={len(members)} selected={len(chosen)}")
        selected.extend(chosen)
    total = sum(int(e["size_bytes"]) for e in selected)
    primary = sum(int(e["naxis1"]) * int(e["naxis2"]) * 2 for e in selected)
    print(f"lunar_rows={len(rows)} eligible={eligible} selected={len(selected)} download_bytes={total} primary_bytes={primary}")
    with args.out.open("w", encoding="utf-8") as handle:
        handle.write("# HDAP Walz lunar plates pinned by scripts/discover.py; see README.md\n")
        handle.write("\t".join(COLUMNS) + "\n")
        for entry in selected:
            handle.write("\t".join(entry[c] for c in COLUMNS) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
