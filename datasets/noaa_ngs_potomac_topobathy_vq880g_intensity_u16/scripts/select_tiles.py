#!/usr/bin/env python3
"""Deterministic tile selection from saved S3 ListObjectsV2 pages (discover.sh).

Population: every laz/geoid18/8727/deliveryNN/*.copc.laz key. Eligible tiles
are 10,000,000..25,000,000 bytes (avoids ~100 KB edge slivers and keeps the
download bounded). Per delivery, eligible keys are sorted by name (flight
date first, then easting/northing) and PER_DELIVERY keys are taken at evenly
spaced positions i*n/k + n/(2k), which spreads the picks over the flight
dates in proportion to their eligible tile counts.
Output columns: delivery, tile, size_bytes, etag, last_modified, url
Usage: select_tiles.py PAGES_DIR OUT_TSV [--exclude TILE ...]
"""
import argparse
import glob
import os
import re

BASE = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/"
PREFIX = "laz/geoid18/8727/"
MIN_BYTES, MAX_BYTES = 10_000_000, 25_000_000
PER_DELIVERY = 24


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pages")
    ap.add_argument("out")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="tiles (deliveryNN/name) rejected by the decode probe")
    a = ap.parse_args()
    rows = {}
    for page in sorted(glob.glob(os.path.join(a.pages, "*.xml"))):
        text = open(page, encoding="utf-8").read()
        for c in re.findall(r"<Contents>(.*?)</Contents>", text, re.S):
            key = re.search(r"<Key>(.*?)</Key>", c).group(1)
            m = re.fullmatch(re.escape(PREFIX) + r"(delivery\d\d)/([^/]+\.copc\.laz)", key)
            if not m:
                continue
            size = int(re.search(r"<Size>(\d+)</Size>", c).group(1))
            etag = re.search(r"<ETag>(.*?)</ETag>", c).group(1).replace("&quot;", "").strip('"')
            lm = re.search(r"<LastModified>(.*?)</LastModified>", c).group(1)
            rows[key] = (m.group(1), f"{m.group(1)}/{m.group(2)}", size, etag, lm)
    print(f"population tiles={len(rows)} bytes={sum(r[2] for r in rows.values())}")
    out = []
    for delivery in sorted({r[0] for r in rows.values()}):
        elig = sorted((r for r in rows.values()
                       if r[0] == delivery and MIN_BYTES <= r[2] <= MAX_BYTES
                       and r[1] not in a.exclude), key=lambda r: r[1])
        n, k = len(elig), PER_DELIVERY
        picks = [elig[(2 * i * n + n) // (2 * k)] for i in range(k)]
        print(f"{delivery}: eligible={n} picked={len(picks)}")
        out.extend(picks)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("delivery\ttile\tsize_bytes\tetag\tlast_modified\turl\n")
        for d, tile, size, etag, lm in out:
            fh.write(f"{d}\t{tile}\t{size}\t{etag}\t{lm}\t{BASE}{PREFIX}{tile}\n")
    print(f"selected tiles={len(out)} bytes={sum(r[2] for r in out)}")


if __name__ == "__main__":
    main()
