#!/usr/bin/env python3
"""Append LAS header facts (from 4 KiB range-GET prefixes) to sources.tsv.

Used only by discover.sh. Each prefix must be a LAS 1.4 header with point data
record format 6 (LASzip compression bit set) and record length 30; the
64-bit point count at byte 247 becomes the pinned point_count column.
"""
import os
import struct
import sys


def main():
    src, prefix_dir, out = sys.argv[1:4]
    lines = open(src, encoding="utf-8").read().splitlines()
    head = lines[0].split("\t")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\t".join(head + ["point_count"]) + "\n")
        total = 0
        for line in lines[1:]:
            row = line.split("\t")
            tile = row[1]
            raw = open(os.path.join(prefix_dir, tile.replace("/", "__")), "rb").read()
            if raw[:4] != b"LASF" or raw[24:26] != b"\x01\x04":
                raise SystemExit(f"{tile}: not a LAS 1.4 header")
            pf = raw[104]
            (rlen,) = struct.unpack_from("<H", raw, 105)
            if pf & 0x3F != 6 or not pf & 0x80 or rlen != 30:
                raise SystemExit(f"{tile}: point format {pf} record length {rlen}")
            (count,) = struct.unpack_from("<Q", raw, 247)
            total += count
            fh.write("\t".join(row + [str(count)]) + "\n")
    print(f"total_points={total}")


if __name__ == "__main__":
    main()
