#!/usr/bin/env python3
"""Independent decoder for ASTER L1T TIR COGs, used only by verify.sh.

Deliberately shares no code with aster_tir_cog.py: tags are read by seeking in
the open file, tiles are inflated with a zlib decompressobj, the TIFF
Predictor-2 inverse is an explicit per-element loop (stride = 5 samples, mod
2**16), and the raster is assembled tile-row by tile-row.  Output is the
row-major, pixel-interleaved little-endian uint16 raster.
"""
from __future__ import annotations

import array
import math
import struct
import sys
import zlib

BANDS = 5


class DecodeError(ValueError):
    pass


def _read_primary_tags(fh) -> dict[int, tuple[int, int, bytes]]:
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
        raise DecodeError(f"tag {tag} is not scalar")
    return vals[0]


def decode_file(path: str) -> tuple[tuple[int, int, int], bytes]:
    with open(path, "rb") as fh:
        e = _read_primary_tags(fh)
        width, height = _one(fh, e, 256), _one(fh, e, 257)
        if _one(fh, e, 277) != BANDS:
            raise DecodeError("SamplesPerPixel != 5")
        if _values(fh, e, 258) != [16] * BANDS:
            raise DecodeError("BitsPerSample != 16 x 5")
        if 339 in e and set(_values(fh, e, 339)) != {1}:
            raise DecodeError("SampleFormat is not unsigned")
        if _one(fh, e, 284, 1) != 1:
            raise DecodeError("not chunky")
        if _one(fh, e, 259) not in (8, 32946):
            raise DecodeError("not Deflate")
        predictor = _one(fh, e, 317, 1)
        if predictor not in (1, 2):
            raise DecodeError(f"predictor {predictor}")
        tw, th = _one(fh, e, 322), _one(fh, e, 323)
        offsets, counts = _values(fh, e, 324), _values(fh, e, 325)
        nx, ny = math.ceil(width / tw), math.ceil(height / th)
        if len(offsets) != nx * ny or len(counts) != nx * ny:
            raise DecodeError("tile table length mismatch")
        tile_len = tw * th * BANDS
        row_len = tw * BANDS
        out = bytearray()
        for ty in range(ny):
            strip = []
            for tx in range(nx):
                k = ty * nx + tx
                if offsets[k] == 0 and counts[k] == 0:
                    strip.append(b"\x00" * (tile_len * 2))  # sparse tile = zero fill
                    continue
                fh.seek(offsets[k])
                inflater = zlib.decompressobj()
                raw = inflater.decompress(fh.read(counts[k])) + inflater.flush()
                if len(raw) != tile_len * 2:
                    raise DecodeError(f"tile {k} inflated to {len(raw)} bytes")
                vals = array.array("H")
                vals.frombytes(raw)
                if sys.byteorder == "big":
                    vals.byteswap()
                if predictor == 2:
                    for r in range(th):
                        start = r * row_len
                        for i in range(start + BANDS, start + row_len):
                            vals[i] = (vals[i] + vals[i - BANDS]) & 0xFFFF
                if sys.byteorder == "big":
                    vals.byteswap()
                strip.append(vals.tobytes())
            rows_here = min(th, height - ty * th)
            for r in range(rows_here):
                for tx, blob in enumerate(strip):
                    cols = min(tw, width - tx * tw)
                    base = r * row_len * 2
                    out += blob[base:base + cols * BANDS * 2]
        if len(out) != width * height * BANDS * 2:
            raise DecodeError("assembled raster has the wrong size")
        return (height, width, BANDS), bytes(out)
