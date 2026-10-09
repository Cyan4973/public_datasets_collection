#!/usr/bin/env python3
"""Append the LAS 1.4 header point count (and layout check) to sources.tsv.

Reads OUT_DIR/headers/<tile>.hdr (first 375 bytes of each selected tile, one
HTTP range request each) and rewrites sources.tsv with a header_point_count
column. The WFS nombre_points is a catalogue figure that differs from the
file header by a few thousand points, so the header value is what is pinned.
"""
import os
import struct
import sys

src, hdr_dir = sys.argv[1], sys.argv[2]
lines = open(src, encoding="utf-8").read().splitlines()
head = lines[0].split("\t")
if "header_point_count" in head:
    head = head[:head.index("header_point_count")]
out = ["\t".join(head + ["header_point_count"])]
for line in lines[1:]:
    f = line.split("\t")[:len(head)]
    raw = open(os.path.join(hdr_dir, f[0] + ".hdr"), "rb").read()
    if len(raw) < 375 or raw[:4] != b"LASF":
        raise SystemExit(f"{f[0]}: bad header bytes")
    vmaj, vmin = raw[24], raw[25]
    fmt, rlen = raw[104], struct.unpack_from("<H", raw, 105)[0]
    (count,) = struct.unpack_from("<Q", raw, 247)
    if (vmaj, vmin) != (1, 4) or fmt & 0x3F != 6 or not fmt & 0x80 or rlen != 30:
        raise SystemExit(f"{f[0]}: unexpected layout {vmaj}.{vmin} fmt={fmt} rlen={rlen}")
    wfs = int(f[2])
    if abs(count - wfs) > 0.01 * wfs:
        raise SystemExit(f"{f[0]}: header count {count} far from WFS {wfs}")
    out.append("\t".join(f + [str(count)]))
open(src, "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"pinned header counts for {len(out) - 1} tiles")
