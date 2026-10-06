#!/usr/bin/env python3
"""Pure-stdlib reader for the Planetary Computer ASTER L1T TIR COGs.

The Microsoft Planetary Computer `aster-l1t` collection stores the five ASTER
thermal-infrared bands (ImageData10..ImageData14, 8.3-11.65 um) of every
AST_L1T v003 scene as one Cloud-Optimized GeoTIFF asset `TIR`: a classic
little-endian TIFF whose primary IFD holds a 5-sample-per-pixel uint16 raster
(PlanarConfiguration 1 = chunky / pixel-interleaved), Deflate-compressed in
square tiles with TIFF Predictor 2 (horizontal differencing).  For a chunky
image the predictor differences each sample against the *same band* of the
previous pixel, i.e. with a stride of SamplesPerPixel (= 5) uint16 elements,
modulo 2**16.  Overview IFDs that follow the primary IFD are ignored.

This module validates the primary IFD and rebuilds the full raster in source
order: rows north to south, columns west to east, and the five band values of
each pixel adjacent (band 10 first).  Edge tiles are cropped to the image.

Usage:
    aster_tir_cog.py validate <TIR.tif>      header + every tile inflates (JSON)
    aster_tir_cog.py selftest                synthetic round-trip of both decoders
"""
from __future__ import annotations

import array
import itertools
import json
import math
import re
import struct
import sys
import zlib

SPP = 5
BAND_NAMES = ["ImageData10", "ImageData11", "ImageData12", "ImageData13", "ImageData14"]

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q"}


class CogError(ValueError):
    pass


def _entry_value(data: bytes, field_type: int, count: int, raw: bytes):
    size = TYPE_SIZE.get(field_type)
    if size is None:
        raise CogError(f"unsupported TIFF field type {field_type}")
    nbytes = size * count
    if nbytes <= 4:
        blob = raw[:nbytes]
    else:
        offset = struct.unpack("<I", raw)[0]
        if offset + nbytes > len(data):
            raise CogError(f"TIFF value outside file offset={offset} bytes={nbytes}")
        blob = data[offset:offset + nbytes]
    if field_type == 2:
        return blob.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    fmt = TYPE_FMT.get(field_type)
    if fmt is None:
        return blob
    return list(struct.unpack("<" + fmt * count, blob))


def parse_ifds(data: bytes) -> list[dict[int, object]]:
    if data[:4] != b"II*\x00":
        raise CogError(f"not a classic little-endian TIFF (magic={data[:4]!r})")
    offset = struct.unpack_from("<I", data, 4)[0]
    ifds: list[dict[int, object]] = []
    seen: set[int] = set()
    while offset:
        if offset in seen or offset + 2 > len(data):
            raise CogError(f"invalid IFD chain at offset {offset}")
        seen.add(offset)
        count = struct.unpack_from("<H", data, offset)[0]
        end = offset + 2 + 12 * count
        if end + 4 > len(data):
            raise CogError(f"truncated IFD at offset {offset}")
        tags: dict[int, object] = {}
        for i in range(count):
            pos = offset + 2 + 12 * i
            tag, field_type, n = struct.unpack_from("<HHI", data, pos)
            tags[tag] = _entry_value(data, field_type, n, data[pos + 8:pos + 12])
        ifds.append(tags)
        offset = struct.unpack_from("<I", data, end)[0]
        if len(ifds) > 64:
            raise CogError("too many IFDs")
    return ifds


def _ints(tags: dict[int, object], tag: int, default: list[int] | None = None) -> list[int]:
    value = tags.get(tag)
    if isinstance(value, list) and value:
        return [int(v) for v in value]
    if default is not None:
        return default
    raise CogError(f"missing TIFF tag {tag}")


def _scalar(tags: dict[int, object], tag: int, default: int | None = None) -> int:
    values = _ints(tags, tag, None if default is None else [default])
    if len(values) != 1:
        raise CogError(f"TIFF tag {tag} has {len(values)} values, expected 1")
    return values[0]


def band_descriptions(xml: str) -> list[str]:
    """Per-band descriptions from GDAL_METADATA (role="description" items)."""
    found: dict[int, str] = {}
    for match in re.finditer(r"<Item\b([^>]*)>([^<]*)</Item>", xml):
        attrs, value = match.group(1), match.group(2).strip()
        if 'role="description"' not in attrs:
            continue
        sample = re.search(r'sample="(\d+)"', attrs)
        if sample:
            found[int(sample.group(1))] = value
    return [found[i] for i in sorted(found)]


def check_band_order(xml: str) -> list[str]:
    """Require the five TIR bands ImageData10..14 in sample order 0..4."""
    descriptions = band_descriptions(xml)
    if descriptions:
        if len(descriptions) != SPP or any(name not in desc for name, desc in zip(BAND_NAMES, descriptions)):
            raise CogError(f"band descriptions {descriptions} do not name {BAND_NAMES} in order")
        return descriptions
    # Fallback: the band names must at least appear in band order.
    positions = [xml.find(name) for name in BAND_NAMES]
    if any(p < 0 for p in positions) or positions != sorted(positions):
        raise CogError(f"GDAL metadata does not list {BAND_NAMES} in order")
    return list(BAND_NAMES)


def structure(data: bytes) -> dict:
    """Validate the primary IFD; return its structure plus the tile tables."""
    ifds = parse_ifds(data)
    tags = ifds[0]
    if _scalar(tags, 254, 0) != 0:
        raise CogError("first IFD is not the full-resolution image")
    width, height = _scalar(tags, 256), _scalar(tags, 257)
    spp = _scalar(tags, 277, 1)
    if spp != SPP:
        raise CogError(f"SamplesPerPixel {spp}, expected {SPP}")
    bps = _ints(tags, 258)
    if bps != [16] * SPP:
        raise CogError(f"BitsPerSample {bps}, expected {[16] * SPP}")
    sample_format = _ints(tags, 339, [1] * SPP)
    if sample_format not in ([1] * SPP, [1]):
        raise CogError(f"SampleFormat {sample_format}, expected unsigned integer")
    planar = _scalar(tags, 284, 1)
    if planar != 1:
        raise CogError(f"PlanarConfiguration {planar}, expected 1 (chunky)")
    compression = _scalar(tags, 259, 1)
    if compression not in (8, 32946):
        raise CogError(f"Compression {compression}, expected Deflate (8)")
    predictor = _scalar(tags, 317, 1)
    if predictor not in (1, 2):
        raise CogError(f"Predictor {predictor}, expected 1 or 2")
    if 322 not in tags or 323 not in tags:
        raise CogError("primary image is not tiled")
    tw, th = _scalar(tags, 322), _scalar(tags, 323)
    if tw <= 0 or th <= 0 or tw % 16 or th % 16:
        raise CogError(f"invalid tile size {tw}x{th}")
    if width <= 0 or height <= 0:
        raise CogError(f"invalid image size {width}x{height}")
    across, down = math.ceil(width / tw), math.ceil(height / th)
    offsets, counts = _ints(tags, 324), _ints(tags, 325)
    if len(offsets) != across * down or len(counts) != across * down:
        raise CogError(f"tile table sizes {len(offsets)}/{len(counts)} != {across * down}")
    sparse = 0
    for index, (off, cnt) in enumerate(zip(offsets, counts)):
        if off == 0 and cnt == 0:
            sparse += 1  # GDAL sparse tile: never written, reads as all zero (fill)
            continue
        if cnt <= 0 or off <= 0 or off + cnt > len(data):
            raise CogError(f"tile {index} outside file offset={off} bytes={cnt}")
    if sparse == len(offsets):
        raise CogError("every primary tile is sparse")
    for level, ifd in enumerate(ifds[1:], 1):
        if _scalar(ifd, 254, 0) & 1 != 1:
            raise CogError(f"IFD {level} is not a reduced-resolution overview")
    xml = tags.get(42112)
    if not isinstance(xml, str) or "<GDALMetadata>" not in xml:
        raise CogError("missing GDAL_METADATA tag 42112")
    descriptions = check_band_order(xml)
    nodata = tags.get(42113)
    return {
        "width": width,
        "height": height,
        "samples_per_pixel": spp,
        "bits_per_sample": 16,
        "sample_format": 1,
        "planar_configuration": planar,
        "compression": compression,
        "predictor": predictor,
        "photometric": _scalar(tags, 262, 1),
        "tile_width": tw,
        "tile_height": th,
        "tiles_across": across,
        "tiles_down": down,
        "ifd_count": len(ifds),
        "sparse_tiles": sparse,
        "gdal_nodata": nodata.strip() if isinstance(nodata, str) else None,
        "band_descriptions": descriptions,
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


def undo_predictor2(values: array.array, tile_width: int, tile_height: int, spp: int) -> None:
    """In place: per row, cumulative sum of each band's samples (stride spp), mod 2**16."""
    row_len = tile_width * spp
    for r in range(tile_height):
        base = r * row_len
        end = base + row_len
        for band in range(spp):
            acc = itertools.accumulate(values[base + band:end:spp])
            values[base + band:end:spp] = array.array("H", [v & 0xFFFF for v in acc])


def decode(data: bytes, info: dict | None = None) -> bytes:
    """Rebuild the primary raster as little-endian uint16, pixel-interleaved."""
    info = structure(data) if info is None else info
    width, height = info["width"], info["height"]
    tw, th, across = info["tile_width"], info["tile_height"], info["tiles_across"]
    pixel_bytes = SPP * 2
    tile_bytes = tw * th * pixel_bytes
    row_bytes = width * pixel_bytes
    out = bytearray(height * row_bytes)
    for index, (off, cnt) in enumerate(zip(info["tile_offsets"], info["tile_byte_counts"])):
        tile = _inflate(data[off:off + cnt], tile_bytes, index)
        if info["predictor"] == 2:
            values = array.array("H")
            values.frombytes(tile)
            if sys.byteorder != "little":
                values.byteswap()
            undo_predictor2(values, tw, th, SPP)
            if sys.byteorder != "little":
                values.byteswap()
            tile = values.tobytes()
        tx, ty = index % across, index // across
        copy_w = min(tw, width - tx * tw) * pixel_bytes
        copy_h = min(th, height - ty * th)
        for r in range(copy_h):
            src = r * tw * pixel_bytes
            dst = (ty * th + r) * row_bytes + tx * tw * pixel_bytes
            out[dst:dst + copy_w] = tile[src:src + copy_w]
    return bytes(out)


def validate(data: bytes) -> dict:
    """Header structure plus a full inflate of every primary tile (no predictor undo)."""
    info = structure(data)
    tile_bytes = info["tile_width"] * info["tile_height"] * SPP * 2
    for index, (off, cnt) in enumerate(zip(info["tile_offsets"], info["tile_byte_counts"])):
        _inflate(data[off:off + cnt], tile_bytes, index)
    return public_structure(info)


# ---------------------------------------------------------------------------
# Synthetic self-test: an independent TIFF *writer* (forward predictor) and a
# round trip through this decoder and the separate verify decoder.

def _encode_predictor2(values: list[int], tile_width: int, tile_height: int, spp: int) -> list[int]:
    out = list(values)
    row_len = tile_width * spp
    for r in range(tile_height):
        base = r * row_len
        for i in range(row_len - 1, spp - 1, -1):
            out[base + i] = (values[base + i] - values[base + i - spp]) & 0xFFFF
    return out


def synthetic_tiff(width: int, height: int, tile: int, predictor: int, seed: int,
                   descriptions: bool = True, sparse: tuple[int, ...] = (),
                   raster: list[int] | None = None) -> tuple[bytes, bytes]:
    """Return (tiff_bytes, expected_raster_le) for a chunky 5-band uint16 image."""
    import random

    rng = random.Random(seed)
    generate = raster is None
    raster = [0] * (width * height * SPP) if raster is None else list(raster)
    for y in (range(height) if generate else ()):
        for x in range(width):
            inside = (x + 2 * y) % 29 > 6  # diagonal fill stripes, like a rotated swath edge
            for b in range(SPP):
                if inside:
                    v = 900 + 150 * b + 40 * ((x * 7 + y * 3) % 13) + rng.randint(-30, 30)
                    if (x + y + b) % 17 == 0:
                        v = 4095  # large jumps force negative differences (mod 2**16)
                    raster[(y * width + x) * SPP + b] = v
    across, down = math.ceil(width / tile), math.ceil(height / tile)
    for k in sparse:  # a sparse tile reads as zero: blank its image area
        tx, ty = k % across, k // across
        for y in range(ty * tile, min(height, (ty + 1) * tile)):
            for x in range(tx * tile, min(width, (tx + 1) * tile)):
                raster[(y * width + x) * SPP:(y * width + x + 1) * SPP] = [0] * SPP
    tiles: list[bytes] = []
    for ty in range(down):
        for tx in range(across):
            block = [0] * (tile * tile * SPP)
            for r in range(tile):
                y = ty * tile + r
                for c in range(tile):
                    x = tx * tile + c
                    if y < height and x < width:
                        src = (y * width + x) * SPP
                        dst = (r * tile + c) * SPP
                        block[dst:dst + SPP] = raster[src:src + SPP]
                    else:  # padding beyond the image edge must be cropped away
                        dst = (r * tile + c) * SPP
                        block[dst:dst + SPP] = [7, 7, 7, 7, 7]
            if predictor == 2:
                block = _encode_predictor2(block, tile, tile, SPP)
            tiles.append(zlib.compress(struct.pack(f"<{len(block)}H", *block), 6))

    if descriptions:
        items = "".join(f'<Item name="DESCRIPTION" sample="{i}" role="description">{n}</Item>'
                        for i, n in enumerate(BAND_NAMES))
    else:
        items = "".join(f'<Item name="BAND_NAME" sample="{i}">{n}</Item>' for i, n in enumerate(BAND_NAMES))
    xml = f"<GDALMetadata>{items}</GDALMetadata>".encode() + b"\x00"

    def build_ifd(entries: list, data_offset: int, next_ifd: int) -> bytes:
        """IFD bytes (count, entries, next pointer) followed by its out-of-line values."""
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

    def layout(tile_start: int) -> tuple[bytes, int]:
        offsets, cursor = [], tile_start
        for k, t in enumerate(tiles):
            offsets.append(0 if k in sparse else cursor)
            cursor += 0 if k in sparse else len(t)
        primary = [
            (254, 4, [0]), (256, 4, [width]), (257, 4, [height]), (258, 3, [16] * SPP), (259, 3, [8]),
            (262, 3, [1]), (277, 3, [SPP]), (284, 3, [1]), (317, 3, [predictor]), (322, 3, [tile]),
            (323, 3, [tile]), (324, 4, offsets),
            (325, 4, [0 if k in sparse else len(t) for k, t in enumerate(tiles)]),
            (338, 3, [0] * (SPP - 1)), (339, 3, [1] * SPP), (42112, 2, xml), (42113, 2, b"0\x00"),
        ]
        overview = [(254, 4, [1]), (256, 4, [1]), (257, 4, [1]), (258, 3, [16] * SPP), (259, 3, [8]),
                    (277, 3, [SPP]), (322, 3, [16]), (323, 3, [16]), (324, 4, [tile_start]), (325, 4, [1])]
        ifd0_at = 8
        ifd0_head = 2 + 12 * len(primary) + 4
        ifd0_size = len(build_ifd(primary, ifd0_at + ifd0_head, 0))
        ovr_at = ifd0_at + ifd0_size + (ifd0_size % 2)
        ovr_head = 2 + 12 * len(overview) + 4
        header = bytearray(b"II*\x00" + struct.pack("<I", ifd0_at))
        header += build_ifd(primary, ifd0_at + ifd0_head, ovr_at)
        header += b"\x00" * (ovr_at - len(header))
        header += build_ifd(overview, ovr_at + ovr_head, 0)
        return bytes(header), len(header)

    _, header_len = layout(0)
    tile_start = header_len + (-header_len % 16)
    header, header_len2 = layout(tile_start)
    if header_len2 != header_len:
        raise RuntimeError("synthetic header size changed between layout passes")
    out = bytearray(header) + b"\x00" * (tile_start - header_len)
    for k, t in enumerate(tiles):
        if k not in sparse:
            out += t
    expected = struct.pack(f"<{len(raster)}H", *raster)
    return bytes(out), expected


def selftest() -> int:
    import os
    import tempfile
    import time

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import tir_independent_decode as independent  # noqa: E402

    cases = [
        (37, 23, 16, 2, 1, True, ()),     # edge tiles in both directions, predictor 2
        (48, 32, 16, 2, 2, False, ()),    # exact tile multiple, fallback band-name check
        (53, 41, 32, 1, 3, True, ()),     # no predictor
        (70, 50, 16, 2, 5, True, (0, 9)), # sparse (never written) corner tiles
        (600, 530, 512, 2, 4, True, ()),  # realistic tile size with 512-px edge crops
    ]
    for width, height, tile, predictor, seed, desc, sparse in cases:
        tiff, expected = synthetic_tiff(width, height, tile, predictor, seed, desc, sparse)
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
        if again != expected or shape != (height, width, SPP):
            raise SystemExit(f"selftest FAIL independent decoder {width}x{height} tile={tile} predictor={predictor}")
        # A stride-1 predictor undo (the classic mistake) must NOT reproduce tile 0.
        if predictor == 2:
            off, cnt = next((o, c) for o, c in zip(info["tile_offsets"], info["tile_byte_counts"]) if c)
            right = array.array("H")
            right.frombytes(zlib.decompress(tiff[off:off + cnt]))
            wrong = array.array("H", right)
            undo_predictor2(right, tile, tile, SPP)
            undo_predictor2(wrong, tile * SPP, tile, 1)
            if wrong == right:
                raise SystemExit("selftest FAIL: stride-1 predictor undo unexpectedly matches")
        if info["sparse_tiles"] != len(sparse):
            raise SystemExit("selftest FAIL: sparse tile count")
        print(f"selftest ok {width}x{height} tile={tile} predictor={predictor} sparse={len(sparse)} "
              f"bytes={len(expected)} build_s={t_build:.2f} verify_s={t_verify:.2f}")
    # Structural rejections.
    tiff, _ = synthetic_tiff(37, 23, 16, 2, 1, True)
    bad = tiff.replace(b">ImageData12<", b">ImageData99<")
    try:
        structure(bad)
    except CogError:
        pass
    else:
        raise SystemExit("selftest FAIL: wrong band order accepted")
    try:
        structure(b"MM\x00*" + tiff[4:])
    except CogError:
        pass
    else:
        raise SystemExit("selftest FAIL: big-endian magic accepted")
    print("selftest ok rejections")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "selftest":
        return selftest()
    if len(argv) != 3 or argv[1] != "validate":
        print(__doc__, file=sys.stderr)
        return 2
    path = argv[2]
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        report = validate(data)
    except CogError as exc:
        print(f"INVALID {path}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
