#!/usr/bin/env python3
"""Independent decoder for Landsat C2 L1 MSS band COGs, used only by verify.sh.

Deliberately shares no code with mss_cog.py: tags are read by seeking in the
open file, tiles are read with explicit seeks and inflated with a zlib
decompressobj, the 8-bit Predictor-2 inverse uses itertools.accumulate, and
the raster is assembled one output row at a time across a whole tile row.
Output is the row-major uint8 raster of IFD 0 (height * width bytes).
"""
from __future__ import annotations

import itertools
import math
import struct
import sys
import zlib


class DecodeError(ValueError):
    pass


def _read_ifd0(fh) -> dict[int, tuple[int, int, bytes]]:
    head = fh.read(8)
    if len(head) != 8 or head[:4] != b"II*\x00":
        raise DecodeError("not a classic little-endian TIFF")
    fh.seek(struct.unpack("<I", head[4:])[0])
    (count,) = struct.unpack("<H", fh.read(2))
    entries = {}
    for _ in range(count):
        tag, typ, n, raw = struct.unpack("<HHI4s", fh.read(12))
        entries[tag] = (typ, n, raw)
    return entries


def _values(fh, entries, tag: int) -> list[int]:
    if tag not in entries:
        raise DecodeError(f"missing tag {tag}")
    typ, n, raw = entries[tag]
    fmt = {3: "H", 4: "I"}.get(typ)
    if fmt is None:
        raise DecodeError(f"tag {tag} has unexpected type {typ}")
    size = struct.calcsize(fmt) * n
    if size <= 4:
        return list(struct.unpack("<" + fmt * n, raw[:size]))
    here = fh.tell()
    fh.seek(struct.unpack("<I", raw)[0])
    blob = fh.read(size)
    fh.seek(here)
    if len(blob) != size:
        raise DecodeError(f"tag {tag} values truncated")
    return list(struct.unpack("<" + fmt * n, blob))


def _one(fh, entries, tag: int, default: int | None = None) -> int:
    if tag not in entries and default is not None:
        return default
    vals = _values(fh, entries, tag)
    if len(vals) != 1:
        raise DecodeError(f"tag {tag} has {len(vals)} values")
    return vals[0]


def _ascii(fh, entries, tag: int) -> str | None:
    if tag not in entries:
        return None
    typ, n, raw = entries[tag]
    if typ != 2:
        raise DecodeError(f"tag {tag} is not ASCII")
    if n <= 4:
        blob = raw[:n]
    else:
        here = fh.tell()
        fh.seek(struct.unpack("<I", raw)[0])
        blob = fh.read(n)
        fh.seek(here)
    return blob.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def decode_file(path: str) -> tuple[tuple[int, int], bytes]:
    """Return ((height, width), raster bytes) for IFD 0 of a uint8 MSS band COG."""
    with open(path, "rb") as fh:
        entries = _read_ifd0(fh)
        if _one(fh, entries, 254, 0) != 0:
            raise DecodeError("IFD 0 is not full resolution")
        width, height = _one(fh, entries, 256), _one(fh, entries, 257)
        if _one(fh, entries, 277, 1) != 1 or _values(fh, entries, 258) != [8]:
            raise DecodeError("expected one 8-bit sample per pixel")
        if _one(fh, entries, 339, 1) != 1:
            raise DecodeError("expected unsigned integer samples")
        if _one(fh, entries, 259, 1) not in (8, 32946):
            raise DecodeError("expected Deflate compression")
        predictor = _one(fh, entries, 317, 1)
        if predictor not in (1, 2):
            raise DecodeError(f"unsupported predictor {predictor}")
        if _ascii(fh, entries, 42113) != "0":
            raise DecodeError("GDAL_NODATA is not '0'")
        tw, th = _one(fh, entries, 322), _one(fh, entries, 323)
        offsets, counts = _values(fh, entries, 324), _values(fh, entries, 325)
        across, down = math.ceil(width / tw), math.ceil(height / th)
        if len(offsets) != across * down or len(counts) != across * down:
            raise DecodeError("tile table size mismatch")
        rows: list[bytes] = []
        for ty in range(down):
            # Inflate every tile of this tile row, then emit output rows.
            strip = []
            for tx in range(across):
                k = ty * across + tx
                if offsets[k] == 0 and counts[k] == 0:
                    tile = bytes(tw * th)
                else:
                    fh.seek(offsets[k])
                    payload = fh.read(counts[k])
                    if len(payload) != counts[k]:
                        raise DecodeError(f"tile {k} truncated")
                    d = zlib.decompressobj()
                    tile = d.decompress(payload) + d.flush()
                    if len(tile) != tw * th or not d.eof:
                        raise DecodeError(f"tile {k} inflated to {len(tile)} bytes")
                if predictor == 2:
                    rebuilt = bytearray()
                    for r in range(th):
                        line = tile[r * tw:(r + 1) * tw]
                        rebuilt += bytes(v & 0xFF for v in itertools.accumulate(line))
                    tile = bytes(rebuilt)
                strip.append(tile)
            for r in range(min(th, height - ty * th)):
                line = b"".join(t[r * tw:(r + 1) * tw] for t in strip)
                rows.append(line[:width])
    raster = b"".join(rows)
    if len(raster) != width * height:
        raise DecodeError("assembled raster has the wrong size")
    return (height, width), raster


if __name__ == "__main__":
    shape, data = decode_file(sys.argv[1])
    print(f"shape={shape} bytes={len(data)} zeros={data.count(0)}")
