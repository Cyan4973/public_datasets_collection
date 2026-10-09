"""Pure-stdlib reader for Sentinel-2 C1 L2A SNW_20m Cloud Optimized GeoTIFFs.

Only the exact layout of these assets is accepted (anything else is fatal):
classic little-endian TIFF, IFD0 = full-resolution 5490x5490 grid,
BitsPerSample 8, SamplesPerPixel 1, SampleFormat 1 (uint), Compression 8
(Deflate/zlib), Predictor 2 (horizontal differencing), PlanarConfig 1,
512x512 tiles (11x11 = 121), GDAL_NODATA "0". Overview IFDs are ignored.
"""
from __future__ import annotations

import re
import struct
import zlib
from itertools import accumulate

WIDTH = HEIGHT = 5490
TILE = 512
TYPE_FMT = {1: "B", 2: "s", 3: "H", 4: "I", 12: "d", 16: "Q"}
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 12: 8, 16: 8}
_AND255 = (255).__and__


class SnwFormatError(ValueError):
    pass


def read_ifd0(data: bytes) -> dict[int, object]:
    if data[:4] != b"II*\x00":
        raise SnwFormatError("not a classic little-endian TIFF")
    off = struct.unpack_from("<I", data, 4)[0]
    n = struct.unpack_from("<H", data, off)[0]
    tags: dict[int, object] = {}
    for i in range(n):
        pos = off + 2 + i * 12
        tag, ftype, count = struct.unpack_from("<HHI", data, pos)
        if ftype not in TYPE_FMT:
            continue
        size = TYPE_SIZE[ftype] * count
        if size <= 4:
            raw = data[pos + 8:pos + 8 + size]
        else:
            voff = struct.unpack_from("<I", data, pos + 8)[0]
            raw = data[voff:voff + size]
            if len(raw) != size:
                raise SnwFormatError(f"tag {tag} value runs past end of file")
        if ftype == 2:
            tags[tag] = raw.rstrip(b"\x00").decode("latin1")
        else:
            tags[tag] = struct.unpack("<" + TYPE_FMT[ftype] * count, raw)
    return tags


def layout(data: bytes) -> dict[str, object]:
    t = read_ifd0(data)

    def one(tag: int, default: int | None = None) -> int:
        v = t.get(tag)
        if v is None:
            if default is None:
                raise SnwFormatError(f"missing TIFF tag {tag}")
            return default
        return int(v[0])  # type: ignore[index]

    want = {256: WIDTH, 257: HEIGHT, 258: 8, 259: 8, 277: 1, 317: 2, 322: TILE, 323: TILE}
    for tag, value in want.items():
        got = one(tag)
        if got != value:
            raise SnwFormatError(f"TIFF tag {tag}={got}, expected {value}")
    if one(284, 1) != 1 or one(339, 1) != 1:
        raise SnwFormatError("unexpected PlanarConfiguration or SampleFormat")
    offsets = list(t.get(324, ()))  # type: ignore[arg-type]
    counts = list(t.get(325, ()))  # type: ignore[arg-type]
    across = (WIDTH + TILE - 1) // TILE
    down = (HEIGHT + TILE - 1) // TILE
    if len(offsets) != across * down or len(counts) != across * down:
        raise SnwFormatError(f"tile table has {len(offsets)}/{len(counts)} entries, expected {across * down}")
    for o, c in zip(offsets, counts):
        if c <= 0 or o + c > len(data):
            raise SnwFormatError("tile byte range outside file (truncated?)")
    nodata = t.get(42113)
    if nodata != "0":
        raise SnwFormatError(f"GDAL_NODATA is {nodata!r}, expected '0'")
    meta = t.get(42112, "")
    stats = {k: float(v) for k, v in re.findall(r'<Item name="STATISTICS_(\w+)" sample="0">([^<]+)</Item>', str(meta))}
    return {"offsets": offsets, "counts": counts, "across": across, "down": down, "stats": stats}


def decode(data: bytes) -> bytes:
    """Return the 5490x5490 uint8 grid, row-major (y, x)."""
    lay = layout(data)
    out = bytearray(WIDTH * HEIGHT)
    across = int(lay["across"])  # type: ignore[arg-type]
    for idx, (o, c) in enumerate(zip(lay["offsets"], lay["counts"])):  # type: ignore[arg-type]
        try:
            raw = zlib.decompress(data[o:o + c])
        except zlib.error as exc:
            raise SnwFormatError(f"tile {idx}: corrupt Deflate stream: {exc}") from exc
        if len(raw) != TILE * TILE:
            raise SnwFormatError(f"tile {idx}: inflated to {len(raw)} bytes, expected {TILE * TILE}")
        ty, tx = divmod(idx, across)
        x0, y0 = tx * TILE, ty * TILE
        cw = min(TILE, WIDTH - x0)
        ch = min(TILE, HEIGHT - y0)
        for r in range(ch):
            # predictor 2: running byte-wise sum along the row, modulo 256
            row = bytes(map(_AND255, accumulate(raw[r * TILE:(r + 1) * TILE])))
            dst = (y0 + r) * WIDTH + x0
            out[dst:dst + cw] = row[:cw]
    return bytes(out)
