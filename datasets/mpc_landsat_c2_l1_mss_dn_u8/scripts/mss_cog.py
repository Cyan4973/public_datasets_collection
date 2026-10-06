#!/usr/bin/env python3
"""Pure-stdlib reader for the Planetary Computer Landsat C2 L1 MSS band COGs.

Every Landsat Collection 2 Level-1 MSS band (B1 green, B2 red, B3 nir08,
B4 nir09 for Landsat 4/5) is one Cloud-Optimized GeoTIFF: a classic
little-endian TIFF whose first IFD holds a single-sample uint8 raster
(BitsPerSample 8, SampleFormat 1, PhotometricInterpretation 1), Deflate
compressed in square tiles, GDAL_NODATA "0".  Reduced-resolution overview IFDs
follow it and are ignored.  The probe of 2026-10-06 found Predictor 1 and
256 x 256 tiles; Predictor 2 (8-bit horizontal differencing, mod 256) is also
supported so that a re-export would still decode exactly.

This module validates IFD 0 and rebuilds the full raster: rows north to
south, columns west to east, one byte per pixel, edge-tile padding cropped.

Usage:
    mss_cog.py header <file> [--partial]  IFD-0 structure as JSON; --partial
                                          accepts a truncated prefix (range
                                          probe) and skips tile-extent checks
    mss_cog.py validate <file>            header + every tile inflates (JSON)
    mss_cog.py selftest                   synthetic round trip of both decoders
"""
from __future__ import annotations

import json
import math
import struct
import sys
import zlib

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q"}


class CogError(ValueError):
    pass


def _entry_value(data: bytes, field_type: int, count: int, raw: bytes, partial: bool):
    size = TYPE_SIZE.get(field_type)
    if size is None:
        raise CogError(f"unsupported TIFF field type {field_type}")
    nbytes = size * count
    if nbytes <= 4:
        blob = raw[:nbytes]
    else:
        offset = struct.unpack("<I", raw)[0]
        if offset + nbytes > len(data):
            if partial:
                return None  # value lies beyond the probed prefix
            raise CogError(f"TIFF value outside file offset={offset} bytes={nbytes}")
        blob = data[offset:offset + nbytes]
    if field_type == 2:
        return blob.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    fmt = TYPE_FMT.get(field_type)
    if fmt is None:
        return blob
    return list(struct.unpack("<" + fmt * count, blob))


def parse_ifds(data: bytes, partial: bool = False) -> list[dict[int, object]]:
    """All IFDs (only those fully inside `data` when partial)."""
    if data[:4] != b"II*\x00":
        raise CogError(f"not a classic little-endian TIFF (magic={data[:4]!r})")
    offset = struct.unpack_from("<I", data, 4)[0]
    ifds: list[dict[int, object]] = []
    seen: set[int] = set()
    while offset:
        if offset in seen:
            raise CogError(f"IFD loop at offset {offset}")
        if offset + 2 > len(data):
            if partial and ifds:
                break
            raise CogError(f"invalid IFD offset {offset}")
        seen.add(offset)
        count = struct.unpack_from("<H", data, offset)[0]
        end = offset + 2 + 12 * count
        if end + 4 > len(data):
            if partial and ifds:
                break
            raise CogError(f"truncated IFD at offset {offset}")
        tags: dict[int, object] = {}
        for i in range(count):
            pos = offset + 2 + 12 * i
            tag, field_type, n = struct.unpack_from("<HHI", data, pos)
            tags[tag] = _entry_value(data, field_type, n, data[pos + 8:pos + 12], partial)
        ifds.append(tags)
        offset = struct.unpack_from("<I", data, end)[0]
        if len(ifds) > 64:
            raise CogError("too many IFDs")
    return ifds


def _ints(tags: dict[int, object], tag: int, default: list[int] | None = None) -> list[int]:
    value = tags.get(tag)
    if isinstance(value, list) and value:
        return [int(v) for v in value]
    if value is None and tag in tags:
        raise CogError(f"TIFF tag {tag} lies outside the probed bytes")
    if default is not None:
        return default
    raise CogError(f"missing TIFF tag {tag}")


def _scalar(tags: dict[int, object], tag: int, default: int | None = None) -> int:
    values = _ints(tags, tag, None if default is None else [default])
    if len(values) != 1:
        raise CogError(f"TIFF tag {tag} has {len(values)} values, expected 1")
    return values[0]


def structure(data: bytes, partial: bool = False) -> dict:
    """Validate IFD 0 (single-band uint8 tiled Deflate); return it with the tile tables."""
    ifds = parse_ifds(data, partial)
    tags = ifds[0]
    if _scalar(tags, 254, 0) != 0:
        raise CogError("first IFD is not the full-resolution image")
    width, height = _scalar(tags, 256), _scalar(tags, 257)
    if width <= 0 or height <= 0:
        raise CogError(f"invalid image size {width}x{height}")
    spp = _scalar(tags, 277, 1)
    if spp != 1:
        raise CogError(f"SamplesPerPixel {spp}, expected 1")
    bps = _ints(tags, 258)
    if bps != [8]:
        raise CogError(f"BitsPerSample {bps}, expected [8] (uint8 MSS band)")
    sample_format = _scalar(tags, 339, 1)
    if sample_format != 1:
        raise CogError(f"SampleFormat {sample_format}, expected 1 (unsigned integer)")
    photometric = _scalar(tags, 262, 1)
    if photometric != 1:
        raise CogError(f"PhotometricInterpretation {photometric}, expected 1 (BlackIsZero)")
    planar = _scalar(tags, 284, 1)
    if planar != 1:
        raise CogError(f"PlanarConfiguration {planar}, expected 1")
    compression = _scalar(tags, 259, 1)
    if compression not in (8, 32946):
        raise CogError(f"Compression {compression}, expected Deflate (8)")
    predictor = _scalar(tags, 317, 1)
    if predictor not in (1, 2):
        raise CogError(f"Predictor {predictor}, expected 1 or 2")
    if 322 not in tags or 323 not in tags:
        raise CogError("IFD 0 is not tiled")
    tw, th = _scalar(tags, 322), _scalar(tags, 323)
    if tw <= 0 or th <= 0 or tw % 16 or th % 16:
        raise CogError(f"invalid tile size {tw}x{th}")
    across, down = math.ceil(width / tw), math.ceil(height / th)
    offsets, counts = _ints(tags, 324), _ints(tags, 325)
    if len(offsets) != across * down or len(counts) != across * down:
        raise CogError(f"tile table sizes {len(offsets)}/{len(counts)} != {across * down}")
    sparse = 0
    for index, (off, cnt) in enumerate(zip(offsets, counts)):
        if off == 0 and cnt == 0:
            sparse += 1  # GDAL sparse tile: never written, reads as all zero (fill)
            continue
        if cnt <= 0 or off <= 0:
            raise CogError(f"tile {index} invalid offset={off} bytes={cnt}")
        if not partial and off + cnt > len(data):
            raise CogError(f"tile {index} outside file offset={off} bytes={cnt}")
    if sparse == len(offsets):
        raise CogError("every IFD-0 tile is sparse")
    for level, ifd in enumerate(ifds[1:], 1):
        if _scalar(ifd, 254, 0) & 1 != 1:
            raise CogError(f"IFD {level} is not a reduced-resolution overview")
    nodata = tags.get(42113)
    nodata = nodata.strip() if isinstance(nodata, str) else None
    if nodata != "0":
        raise CogError(f"GDAL_NODATA {nodata!r}, expected '0'")
    pixel_scale = tags.get(33550)
    return {
        "width": width,
        "height": height,
        "bits_per_sample": 8,
        "sample_format": sample_format,
        "photometric": photometric,
        "compression": compression,
        "predictor": predictor,
        "tile_width": tw,
        "tile_height": th,
        "tiles_across": across,
        "tiles_down": down,
        "ifd_count": len(ifds),
        "sparse_tiles": sparse,
        "gdal_nodata": nodata,
        "pixel_scale": [float(v) for v in pixel_scale[:2]] if isinstance(pixel_scale, list) else None,
        "tile_offsets": offsets,
        "tile_byte_counts": counts,
    }


def public_structure(info: dict) -> dict:
    return {k: v for k, v in info.items() if k not in ("tile_offsets", "tile_byte_counts")}


def _inflate(payload: bytes, expected: int, index: int) -> bytes:
    if not payload:
        return bytes(expected)  # sparse tile (offset 0, byte count 0)
    try:
        tile = zlib.decompress(payload)
    except zlib.error as exc:
        raise CogError(f"tile {index}: deflate error {exc}") from exc
    if len(tile) != expected:
        raise CogError(f"tile {index}: inflated {len(tile)} bytes, expected {expected}")
    return tile


def undo_predictor2_u8(tile: bytes, tile_width: int, tile_height: int) -> bytes:
    """Per row: running sum of the byte differences, mod 256."""
    out = bytearray(tile)
    for r in range(tile_height):
        base = r * tile_width
        acc = out[base]
        for i in range(base + 1, base + tile_width):
            acc = (acc + out[i]) & 0xFF
            out[i] = acc
    return bytes(out)


def decode(data: bytes, info: dict | None = None) -> bytes:
    """Rebuild IFD 0 as a row-major uint8 raster (height * width bytes)."""
    info = structure(data) if info is None else info
    width, height = info["width"], info["height"]
    tw, th, across = info["tile_width"], info["tile_height"], info["tiles_across"]
    out = bytearray(height * width)
    for index, (off, cnt) in enumerate(zip(info["tile_offsets"], info["tile_byte_counts"])):
        tile = _inflate(data[off:off + cnt], tw * th, index)
        if info["predictor"] == 2:
            tile = undo_predictor2_u8(tile, tw, th)
        tx, ty = index % across, index // across
        copy_w = min(tw, width - tx * tw)
        copy_h = min(th, height - ty * th)
        for r in range(copy_h):
            src = r * tw
            dst = (ty * th + r) * width + tx * tw
            out[dst:dst + copy_w] = tile[src:src + copy_w]
    return bytes(out)


def validate(data: bytes) -> dict:
    """Header structure plus a full inflate of every IFD-0 tile."""
    info = structure(data)
    expected = info["tile_width"] * info["tile_height"]
    for index, (off, cnt) in enumerate(zip(info["tile_offsets"], info["tile_byte_counts"])):
        _inflate(data[off:off + cnt], expected, index)
    return public_structure(info)


# ---------------------------------------------------------------------------
# Synthetic self-test: an independent TIFF *writer* (forward predictor, tile
# padding, sparse tiles, overview IFD) and a round trip through this decoder
# and the separate verify decoder.

def synthetic_tiff(width: int, height: int, tile: int, predictor: int, seed: int,
                   sparse: tuple[int, ...] = (), nodata: bytes = b"0\x00", bps: int = 8,
                   compression: int = 8) -> tuple[bytes, bytes]:
    """Return (tiff_bytes, expected_raster) for a single-band uint8 image."""
    import random

    rng = random.Random(seed)
    raster = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            # Rotated-footprint fill: zero outside a skewed parallelogram.
            inside = (x - y // 4) > width // 8 and (x - y // 4) < width - width // 8
            if inside:
                v = 20 + ((x * 5 + y * 3) % 90) + rng.randint(-6, 6)
                if (x + 2 * y) % 23 == 0:
                    v = 255  # bright spike forces negative byte differences
                raster[y * width + x] = max(1, min(255, v))
    across, down = math.ceil(width / tile), math.ceil(height / tile)
    for k in sparse:  # a sparse tile reads as zero: blank its image area
        tx, ty = k % across, k // across
        for y in range(ty * tile, min(height, (ty + 1) * tile)):
            for x in range(tx * tile, min(width, (tx + 1) * tile)):
                raster[y * width + x] = 0
    tiles: list[bytes] = []
    for ty in range(down):
        for tx in range(across):
            block = bytearray([9]) * (tile * tile)  # padding beyond the edge must be cropped
            for r in range(tile):
                y = ty * tile + r
                if y >= height:
                    continue
                for c in range(tile):
                    x = tx * tile + c
                    if x < width:
                        block[r * tile + c] = raster[y * width + x]
            if predictor == 2:
                enc = bytearray(block)
                for r in range(tile):
                    for c in range(tile - 1, 0, -1):
                        i = r * tile + c
                        enc[i] = (block[i] - block[i - 1]) & 0xFF
                block = enc
            tiles.append(zlib.compress(bytes(block), 6))

    def build_ifd(entries: list, data_offset: int, next_ifd: int) -> bytes:
        ifd = bytearray(struct.pack("<H", len(entries)))
        blob = bytearray()
        for tag, typ, vals in sorted(entries, key=lambda e: e[0]):
            raw = bytes(vals) if typ == 2 else struct.pack("<" + TYPE_FMT[typ] * len(vals), *vals)
            count = len(raw) if typ == 2 else len(vals)
            if len(raw) <= 4:
                ifd += struct.pack("<HHI", tag, typ, count) + raw.ljust(4, b"\x00")
            else:
                ifd += struct.pack("<HHI", tag, typ, count) + struct.pack("<I", data_offset + len(blob))
                blob += raw + (b"\x00" if len(raw) % 2 else b"")
        ifd += struct.pack("<I", next_ifd)
        return bytes(ifd + blob)

    def layout(tile_start: int) -> bytes:
        offsets, cursor = [], tile_start
        for k, t in enumerate(tiles):
            offsets.append(0 if k in sparse else cursor)
            cursor += 0 if k in sparse else len(t)
        primary = [
            (256, 4, [width]), (257, 4, [height]), (258, 3, [bps]), (259, 3, [compression]),
            (262, 3, [1]), (277, 3, [1]), (284, 3, [1]), (317, 3, [predictor]), (322, 3, [tile]),
            (323, 3, [tile]), (324, 4, offsets),
            (325, 4, [0 if k in sparse else len(t) for k, t in enumerate(tiles)]),
            (339, 3, [1]), (33550, 12, [60.0, 60.0, 0.0]), (42113, 2, nodata),
        ]
        overview = [(254, 4, [1]), (256, 4, [1]), (257, 4, [1]), (258, 3, [8]), (259, 3, [8]),
                    (277, 3, [1]), (322, 3, [16]), (323, 3, [16]), (324, 4, [tile_start]), (325, 4, [1]),
                    (42113, 2, b"0\x00")]
        ifd0_at = 8
        ifd0_head = 2 + 12 * len(primary) + 4
        ifd0_size = len(build_ifd(primary, ifd0_at + ifd0_head, 0))
        ovr_at = ifd0_at + ifd0_size + (ifd0_size % 2)
        ovr_head = 2 + 12 * len(overview) + 4
        header = bytearray(b"II*\x00" + struct.pack("<I", ifd0_at))
        header += build_ifd(primary, ifd0_at + ifd0_head, ovr_at)
        header += b"\x00" * (ovr_at - len(header))
        header += build_ifd(overview, ovr_at + ovr_head, 0)
        return bytes(header)

    header_len = len(layout(0))
    tile_start = header_len + (-header_len % 16)
    header = layout(tile_start)
    if len(header) != header_len:
        raise RuntimeError("synthetic header size changed between layout passes")
    out = bytearray(header) + b"\x00" * (tile_start - header_len)
    for k, t in enumerate(tiles):
        if k not in sparse:
            out += t
    return bytes(out), bytes(raster)


def selftest() -> int:
    import os
    import tempfile
    import time

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mss_independent_decode as independent  # noqa: E402

    cases = [
        (37, 23, 16, 1, 1, ()),        # edge tiles both ways, no predictor (the MSS layout)
        (48, 32, 16, 1, 2, ()),        # exact tile multiple
        (53, 41, 32, 2, 3, ()),        # predictor 2 (mod-256 wraparound)
        (70, 50, 16, 1, 5, (0, 9)),    # sparse (never written) tiles
        (300, 270, 256, 1, 4, ()),     # realistic 256-px tiles with edge crops
        (300, 270, 256, 2, 6, (3,)),   # realistic tiles, predictor 2, sparse corner
    ]
    for width, height, tile, predictor, seed, sparse in cases:
        tiff, expected = synthetic_tiff(width, height, tile, predictor, seed, sparse)
        start = time.time()
        info = structure(tiff)
        got = decode(tiff, info)
        t_build = time.time() - start
        if got != expected:
            raise SystemExit(f"selftest FAIL build decoder {width}x{height} tile={tile} predictor={predictor}")
        with tempfile.NamedTemporaryFile(suffix=".tif") as fh:
            fh.write(tiff)
            fh.flush()
            start = time.time()
            shape, again = independent.decode_file(fh.name)
            t_verify = time.time() - start
        if again != expected or shape != (height, width):
            raise SystemExit(f"selftest FAIL independent decoder {width}x{height} tile={tile} predictor={predictor}")
        if info["sparse_tiles"] != len(sparse):
            raise SystemExit("selftest FAIL: sparse tile count")
        # (Edge-tile padding is filled with 9s by the writer; the byte comparison
        # above proves it was cropped.)
        # A header-only prefix (everything before the first tile) must parse with
        # partial=True and give the same structure; without it, it must fail.
        prefix = tiff[:min(o for o in info["tile_offsets"] if o)]
        head = structure(prefix, partial=True)
        if public_structure(head) != public_structure(info):
            raise SystemExit("selftest FAIL: partial header parse differs")
        try:
            structure(prefix)
        except CogError:
            pass
        else:
            raise SystemExit("selftest FAIL: header-only prefix accepted as a full file")
        print(f"selftest ok {width}x{height} tile={tile} predictor={predictor} sparse={len(sparse)} "
              f"bytes={len(expected)} fill={expected.count(0)} build_s={t_build:.3f} verify_s={t_verify:.3f}")
    # A predictor-2 tile decoded as predictor 1 must NOT reproduce the image.
    tiff, expected = synthetic_tiff(53, 41, 32, 2, 3)
    info = structure(tiff)
    info_wrong = dict(info, predictor=1)
    if decode(tiff, info_wrong) == expected:
        raise SystemExit("selftest FAIL: predictor ignored but output still matched")
    # Structural rejections.
    rejections = {
        "16-bit samples": synthetic_tiff(37, 23, 16, 1, 1, bps=16)[0],
        "LZW compression": synthetic_tiff(37, 23, 16, 1, 1, compression=5)[0],
        "missing nodata": synthetic_tiff(37, 23, 16, 1, 1, nodata=b"\x00")[0],
        "nodata 255": synthetic_tiff(37, 23, 16, 1, 1, nodata=b"255\x00")[0],
        "big-endian magic": b"MM\x00*" + synthetic_tiff(37, 23, 16, 1, 1)[0][4:],
    }
    for label, blob in rejections.items():
        try:
            structure(blob)
        except CogError:
            continue
        raise SystemExit(f"selftest FAIL: {label} accepted")
    # A truncated tile stream must fail validation.
    tiff, _ = synthetic_tiff(70, 50, 16, 1, 5)
    try:
        validate(tiff[:-10])
    except CogError:
        pass
    else:
        raise SystemExit("selftest FAIL: truncated file validated")
    print("selftest ok rejections")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "selftest":
        return selftest()
    if len(argv) in (3, 4) and argv[1] == "header":
        partial = len(argv) == 4 and argv[3] == "--partial"
        if len(argv) == 4 and not partial:
            print(__doc__, file=sys.stderr)
            return 2
        with open(argv[2], "rb") as fh:
            data = fh.read()
        try:
            report = public_structure(structure(data, partial=partial))
        except CogError as exc:
            print(f"INVALID {argv[2]}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(report, sort_keys=True))
        return 0
    if len(argv) == 3 and argv[1] == "validate":
        with open(argv[2], "rb") as fh:
            data = fh.read()
        try:
            report = validate(data)
        except CogError as exc:
            print(f"INVALID {argv[2]}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(report, sort_keys=True))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
