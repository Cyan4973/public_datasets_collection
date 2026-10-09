#!/usr/bin/env python3
"""Semantic payload check used by download.sh: uncompressed CDF v2.6+/v3
magic, network encoding, single-file layout, and GDR eof equal to the file
size (detects truncation). The archive writes CDF 2.7 files up to mid-2021
and CDF 3.x files afterwards; both carry Data_version 6."""
import struct
import sys

path, expected = sys.argv[1], int(sys.argv[2])
with open(path, "rb") as f:
    head = f.read(400)
    f.seek(0, 2)
    size = f.tell()
if size != expected:
    sys.exit(f"size {size} != expected {expected}")
m1, m2 = struct.unpack_from(">II", head, 0)
if m2 != 0x0000FFFF or m1 not in (0xCDF26002, 0xCDF30001):
    sys.exit(f"not an uncompressed CDF v2.6+/v3 file: magic {m1:08x} {m2:08x}")
v3 = m1 == 0xCDF30001
o = "q" if v3 else "i"
rs, rt, gdr, ver, rel, enc, flags = struct.unpack_from(f">{o}i{o}4i", head, 8)
if rt != 1 or ver != (3 if v3 else 2) or enc != 1 or not flags & 2:
    sys.exit(f"unexpected CDR: type={rt} version={ver}.{rel} encoding={enc} flags={flags}")
with open(path, "rb") as f:
    f.seek(gdr)
    g = f.read(48)
grs, grt, _r, _z, _a, eof = struct.unpack_from(f">{o}i4{o}", g, 0)
if grt != 2 or eof != size:
    sys.exit(f"GDR type={grt} eof={eof} size={size}")
