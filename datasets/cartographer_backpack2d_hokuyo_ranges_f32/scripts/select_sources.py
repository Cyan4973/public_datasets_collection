#!/usr/bin/env python3
"""Deterministic session selection from discover.sh's bags.tsv.

Rule:
1. Eligible: every backpack_2d bag except those whose data.rst "Known Issues"
   flags gaps in the (horizontal) laser data. "1 gap in vertical laser data"
   only affects the excluded vertical scanner and stays eligible; build.sh and
   verify.sh still reject any horizontal-scan interval above 1 s.
2. Coverage: for each backpack unit (b0, b1, b2) and each floor (OG1, EG, UG),
   take the eligible session with the fewest horizontal scans.
3. Fill: add the remaining eligible sessions in ascending scan count while the
   cumulative primary size (scans x 1079 x 4 bytes) stays <= 950,000,000
   bytes (5% headroom below the 1,000,000,000-byte cap); stop at the first
   session that does not fit.
Output rows are ordered by bag name.
"""
from __future__ import annotations

import sys
from pathlib import Path

BUDGET = 950_000_000
BEAMS = 1079
OUT_COLUMNS = [
    "bag", "unit", "floor", "duration_s", "size_bytes", "md5_base64", "crc32c_base64",
    "gcs_generation", "index_pos", "chunk_count", "scan_count",
]


def main() -> None:
    lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:]]
    if len(rows) != 56:
        raise SystemExit(f"expected 56 bags, found {len(rows)}")
    for row in rows:
        row["scan_count"] = int(row["scan_count"])
        row["primary_bytes"] = row["scan_count"] * BEAMS * 4
    eligible = []
    for row in rows:
        issue = row["known_issues"].lower()
        if "gap" in issue and "vertical" not in issue:
            print(f"excluded bag={row['bag']} issue={row['known_issues']!r}")
            continue
        eligible.append(row)
    eligible.sort(key=lambda row: (row["scan_count"], row["bag"]))
    chosen: dict[str, dict] = {}
    for key in ("unit", "floor"):
        for value in sorted({row[key] for row in rows}):
            first = next(row for row in eligible if row[key] == value)
            chosen[first["bag"]] = first
            print(f"coverage {key}={value} bag={first['bag']} scans={first['scan_count']}")
    total = sum(row["primary_bytes"] for row in chosen.values())
    if total > BUDGET:
        raise SystemExit("coverage sessions alone exceed the budget")
    for row in eligible:
        if row["bag"] in chosen:
            continue
        if total + row["primary_bytes"] > BUDGET:
            print(f"stop at bag={row['bag']} (would reach {total + row['primary_bytes']} bytes)")
            break
        chosen[row["bag"]] = row
        total += row["primary_bytes"]
    selected = sorted(chosen.values(), key=lambda row: row["bag"])
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        out.write("\t".join(OUT_COLUMNS) + "\n")
        for row in selected:
            out.write("\t".join(str(row[column]) for column in OUT_COLUMNS) + "\n")
    download = sum(int(row["size_bytes"]) for row in selected)
    scans = sum(row["scan_count"] for row in selected)
    print(f"selected sessions={len(selected)} scans={scans} primary_bytes={total} download_bytes={download}")


if __name__ == "__main__":
    main()
