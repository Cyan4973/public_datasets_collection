#!/usr/bin/env python3
"""Inspect the tail of a gzip tar without the preceding stream (discovery aid).

A gzip/DEFLATE stream cannot be entered at an arbitrary byte, but a dynamic
Huffman block can be found by brute force: for every byte offset and bit shift
whose block header says BTYPE=2, try raw inflate with a 32 KiB zero preset
dictionary and keep the first start that decodes at least 16 KB without error.
Back-references into the unknown window decode as zeros only in the first
32 KiB of output; tar headers further in are exact. This is how the recipe
confirmed that velodyne_sync/<utime>.bin members follow velodyne_hits.bin in
2013-01-10_vel.tar.gz before committing to the full download.

Usage: probe_tail.py TAIL_BYTES [--dump decoded.bin]
"""
from __future__ import annotations

import argparse
import re
import struct
import zlib
from pathlib import Path


def shifted(buffer: bytes, bits: int) -> bytes:
    if bits == 0:
        return buffer
    return (int.from_bytes(buffer, "little") >> bits).to_bytes(len(buffer), "little")


def find_block(data: bytes, limit: int = 400_000) -> tuple[int, int] | None:
    for offset in range(min(limit, len(data) - 2)):
        for bits in range(8):
            header = (data[offset] >> bits) | ((data[offset + 1] << (8 - bits)) & 0xFF)
            if (header >> 1) & 3 != 2:
                continue
            inflater = zlib.decompressobj(-15, zdict=b"\0" * 32768)
            try:
                out = inflater.decompress(shifted(data[offset : offset + 16384], bits), 200_000)
            except zlib.error:
                continue
            if len(out) > 16_000:
                return offset, bits
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tail", type=Path)
    parser.add_argument("--dump", type=Path)
    args = parser.parse_args()
    data = args.tail.read_bytes()
    print(f"gzip trailer: crc32={data[-8:-4][::-1].hex()} isize_mod_2^32={int.from_bytes(data[-4:], 'little')}")
    found = find_block(data)
    if not found:
        raise SystemExit("no dynamic DEFLATE block start found")
    offset, bits = found
    inflater = zlib.decompressobj(-15, zdict=b"\0" * 32768)
    decoded = inflater.decompress(shifted(data[offset:], bits))
    print(f"block start: tail byte {offset} bit {bits}; decoded {len(decoded)} bytes")
    if args.dump:
        args.dump.write_bytes(decoded)
    for match in re.finditer(rb"[0-9]{4}-[0-9]{2}-[0-9]{2}/[A-Za-z_/]+(?:[0-9]+)?\.bin\0", decoded):
        header = decoded[match.start() : match.start() + 512]
        if len(header) < 512 or header[257:262] != b"ustar":
            continue
        name = header[:100].rstrip(b"\0").decode()
        size = int(header[124:136].rstrip(b"\0 ") or b"0", 8)
        body = decoded[match.start() + 512 : match.start() + 512 + size]
        summary = ""
        if len(body) == size and size % 8 == 0 and size:
            records = list(struct.iter_unpack("<HHHBB", body))
            summary = (
                f" hits={len(records)} x={min(r[0] for r in records)}..{max(r[0] for r in records)}"
                f" y={min(r[1] for r in records)}..{max(r[1] for r in records)}"
                f" z={min(r[2] for r in records)}..{max(r[2] for r in records)}"
                f" laser_id={min(r[4] for r in records)}..{max(r[4] for r in records)}"
                f" z_code0={sum(1 for r in records if r[2] == 0)}"
            )
        print(f"member {name} size={size}{summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
