#!/usr/bin/env python3
"""Select the pinned IVM-A L2-7 days from saved S3 ListObjectsV2 pages.

Usage:
  discover.py next-token PAGE.xml            print NextContinuationToken (or nothing)
  discover.py select --pages P1.xml [P2.xml ...] --count M --out sources.tsv

Selection rule: every key matching
``spdf/cdaweb/data/icon/l2-7_ivm-a/YYYY/icon_l2-7_ivm-a_YYYYMMDD_v06rNNN.nc``
(the IVM-A daily Level-2.7 product, version-6 family; IVM-B lives under a
different prefix and is never listed), one key per day, sorted by key (which
is date order), then the M keys at indexes floor((2k+1)N/(2M)), k = 0..M-1.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET

NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
PREFIX = "spdf/cdaweb/data/icon/l2-7_ivm-a/"
KEY_RE = re.compile(
    r"^spdf/cdaweb/data/icon/l2-7_ivm-a/(\d{4})/icon_l2-7_ivm-a_(\d{8})_(v06r\d{3})\.nc$"
)


def next_token(path: str) -> None:
    root = ET.parse(path).getroot()
    token = root.findtext(f"{NS}NextContinuationToken")
    truncated = root.findtext(f"{NS}IsTruncated") == "true"
    if truncated and token:
        print(token)


def select(pages: list[str], count: int, out: str) -> None:
    rows = {}
    other = 0
    for page in pages:
        root = ET.parse(page).getroot()
        if root.findtext(f"{NS}Prefix") != PREFIX:
            sys.exit(f"{page}: unexpected listing prefix")
        for item in root.findall(f"{NS}Contents"):
            key = item.findtext(f"{NS}Key")
            match = KEY_RE.match(key)
            if not match:
                other += 1
                continue
            year, day, version = match.groups()
            if day[:4] != year:
                sys.exit(f"{key}: year directory disagrees with file date")
            if day in rows:
                sys.exit(f"{key}: more than one file for day {day}")
            rows[day] = (
                day,
                version,
                key,
                int(item.findtext(f"{NS}Size")),
                item.findtext(f"{NS}ETag").strip('"'),
                item.findtext(f"{NS}LastModified"),
            )
    days = sorted(rows)
    total = len(days)
    if total < count:
        sys.exit(f"only {total} IVM-A files listed, need {count}")
    picks = [days[(2 * k + 1) * total // (2 * count)] for k in range(count)]
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("date\tversion\tkey\tsize_bytes\ts3_etag\tlast_modified\n")
        for day in picks:
            handle.write("\t".join(str(field) for field in rows[day]) + "\n")
    print(
        f"listed_ivm_a_files={total} other_keys={other} first={days[0]} last={days[-1]} "
        f"selected={len(picks)} selected_bytes={sum(rows[d][3] for d in picks)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("next-token")
    p.add_argument("page")
    p = sub.add_parser("select")
    p.add_argument("--pages", nargs="+", required=True)
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.cmd == "next-token":
        next_token(args.page)
    else:
        select(args.pages, args.count, args.out)


if __name__ == "__main__":
    main()
