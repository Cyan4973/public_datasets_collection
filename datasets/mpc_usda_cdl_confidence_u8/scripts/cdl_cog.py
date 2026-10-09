#!/usr/bin/env python3
"""Strict pure-stdlib reader for Planetary Computer USDA CDL 2021 confidence COGs.

Used by download.sh (header validation), probe.py (overview screening) and
build.sh (primary-grid decode). verify.sh deliberately uses its own
independent decoder (scripts/verify_samples.py).

Expected layout (checked, not assumed): little-endian classic TIFF, IFD0 is
the 3000x3000 primary grid (uint8, 1 sample, Deflate, predictor 1, 512x512
tiles -> a 6x6 tile grid whose last row/column is padded and cropped), GDAL
nodata 0, followed by reduced-resolution overview IFDs that the build ignores.
"""
from __future__ import annotations

import struct
import sys
import zlib

WIDTH = 3000
HEIGHT = 3000
TILE = 512
VALID_MIN = 0
VALID_MAX = 100
NODATA = 0

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q", 17: "q"}

EXPECTED_PRIMARY = {
    256: WIDTH,   # ImageWidth
    257: HEIGHT,  # ImageLength
    258: 8,       # BitsPerSample
    259: 8,       # Compression: Adobe Deflate
    277: 1,       # SamplesPerPixel
    284: 1,       # PlanarConfiguration: chunky
    317: 1,       # Predictor: none
    322: TILE,    # TileWidth
    323: TILE,    # TileLength
    339: 1,       # SampleFormat: unsigned integer
}
TAG_DEFAULTS = {259: 1, 277: 1, 284: 1, 317: 1, 339: 1}


class CogError(ValueError):
    pass


def parse_ifds(data: bytes, allow_truncated: bool = False) -> list[dict[int, object]]:
    """Parse every IFD of a little-endian classic TIFF into {tag: values}.

    With allow_truncated=True (header-prefix probing) parsing stops at the
    first IFD or out-of-range tag value that is not inside `data`.
    """
    if len(data) < 8 or data[:4] != b"II*\x00":
        raise CogError("not a little-endian classic TIFF")
    offset = struct.unpack_from("<I", data, 4)[0]
    ifds: list[dict[int, object]] = []
    seen: set[int] = set()
    while offset:
        if offset in seen:
            raise CogError(f"IFD loop at {offset}")
        if offset + 2 > len(data):
            if allow_truncated:
                break
            raise CogError(f"invalid IFD offset {offset}")
        seen.add(offset)
        count = struct.unpack_from("<H", data, offset)[0]
        end = offset + 2 + 12 * count
        if end + 4 > len(data):
            if allow_truncated:
                break
            raise CogError(f"truncated IFD at {offset}")
        tags: dict[int, object] = {}
        for index in range(count):
            entry = offset + 2 + 12 * index
            tag, field_type, n = struct.unpack_from("<HHI", data, entry)
            size = TYPE_SIZE.get(field_type)
            if size is None:
                raise CogError(f"unsupported TIFF field type {field_type} for tag {tag}")
            nbytes = size * n
            if nbytes <= 4:
                raw = data[entry + 8:entry + 8 + nbytes]
            else:
                value_offset = struct.unpack_from("<I", data, entry + 8)[0]
                if value_offset + nbytes > len(data):
                    if allow_truncated:
                        tags[tag] = None
                        continue
                    raise CogError(f"tag {tag} values outside file")
                raw = data[value_offset:value_offset + nbytes]
            if field_type == 2:
                tags[tag] = raw.split(b"\x00", 1)[0].decode("latin-1")
            elif field_type in TYPE_FMT:
                tags[tag] = list(struct.unpack("<" + TYPE_FMT[field_type] * n, raw))
            else:
                tags[tag] = raw
        ifds.append(tags)
        offset = struct.unpack_from("<I", data, end)[0]
    return ifds


def scalar(tags: dict[int, object], tag: int) -> int:
    value = tags.get(tag)
    if value is None:
        if tag in TAG_DEFAULTS:
            return TAG_DEFAULTS[tag]
        raise CogError(f"missing TIFF tag {tag}")
    if not isinstance(value, list) or len(value) != 1:
        raise CogError(f"tag {tag} is not a scalar: {value!r}")
    return int(value[0])


def check_primary(ifds: list[dict[int, object]]) -> dict[int, object]:
    """Reject anything whose IFD0 is not the expected 3000x3000 uint8 Deflate grid."""
    if not ifds:
        raise CogError("no IFDs")
    primary = ifds[0]
    actual = {tag: scalar(primary, tag) for tag in EXPECTED_PRIMARY}
    if actual != EXPECTED_PRIMARY:
        raise CogError(f"unexpected primary TIFF structure {actual}")
    if primary.get(254) not in (None, [0]):
        raise CogError("IFD0 is flagged as a reduced-resolution image")
    nodata = primary.get(42113)
    if nodata is not None and str(nodata).strip() != str(NODATA):
        raise CogError(f"GDAL nodata is {nodata!r}, expected {NODATA}")
    tiles_x = -(-WIDTH // TILE)
    tiles_y = -(-HEIGHT // TILE)
    offsets = primary.get(324)
    counts = primary.get(325)
    if not isinstance(offsets, list) or not isinstance(counts, list):
        raise CogError("missing TileOffsets/TileByteCounts")
    if len(offsets) != tiles_x * tiles_y or len(counts) != tiles_x * tiles_y:
        raise CogError(f"expected {tiles_x * tiles_y} tiles, found {len(offsets)}/{len(counts)}")
    return primary


def decode_ifd(data: bytes, tags: dict[int, object]) -> tuple[int, int, bytearray]:
    """Inflate a tiled uint8 IFD, crop the tile padding, return (w, h, row-major bytes)."""
    width = scalar(tags, 256)
    height = scalar(tags, 257)
    tw = scalar(tags, 322)
    th = scalar(tags, 323)
    if scalar(tags, 258) != 8 or scalar(tags, 277) != 1 or scalar(tags, 259) != 8 or scalar(tags, 317) != 1:
        raise CogError("IFD is not single-band uint8 Deflate predictor 1")
    offsets = tags.get(324)
    counts = tags.get(325)
    tiles_x = -(-width // tw)
    tiles_y = -(-height // th)
    if not isinstance(offsets, list) or not isinstance(counts, list) or len(offsets) != tiles_x * tiles_y or len(counts) != len(offsets):
        raise CogError("tile table does not match the tile grid")
    out = bytearray(width * height)
    tile_bytes = tw * th
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            k = ty * tiles_x + tx
            off, cnt = offsets[k], counts[k]
            if cnt == 0:
                raise CogError(f"sparse (empty) tile {k} is not expected")
            if off + cnt > len(data):
                raise CogError(f"tile {k} extends past end of file")
            try:
                raw = zlib.decompress(data[off:off + cnt])
            except zlib.error as exc:
                raise CogError(f"corrupt Deflate tile {k}: {exc}") from exc
            if len(raw) != tile_bytes:
                raise CogError(f"tile {k} inflated to {len(raw)} bytes, expected {tile_bytes}")
            x0 = tx * tw
            y0 = ty * th
            w = min(tw, width - x0)
            h = min(th, height - y0)
            for r in range(h):
                dst = (y0 + r) * width + x0
                out[dst:dst + w] = raw[r * tw:r * tw + w]
    return width, height, out


def check_file(data: bytes) -> dict[int, object]:
    """Full structural check used by download.sh: IFD0 layout, overview chain, tile bounds, CRS."""
    ifds = parse_ifds(data)
    primary = check_primary(ifds)
    for k, (off, cnt) in enumerate(zip(primary[324], primary[325])):
        if cnt == 0 or off + cnt > len(data):
            raise CogError(f"primary tile {k} empty or outside file")
    sizes = [(scalar(t, 256), scalar(t, 257)) for t in ifds[1:]]
    for (w, h), t in zip(sizes, ifds[1:]):
        if t.get(254) != [1] or w >= WIDTH or h >= HEIGHT:
            raise CogError(f"unexpected non-overview IFD {w}x{h}")
    citation = str(primary.get(34737, ""))
    if "Albers" not in citation or "NAD83" not in citation:
        raise CogError(f"unexpected GeoTIFF citation {citation!r}")
    pixel_scale = primary.get(33550)
    if not isinstance(pixel_scale, list) or [round(v, 6) for v in pixel_scale[:2]] != [30.0, 30.0]:
        raise CogError(f"unexpected pixel scale {pixel_scale!r}")
    return primary


def decode_primary(data: bytes) -> bytearray:
    ifds = parse_ifds(data)
    primary = check_primary(ifds)
    width, height, grid = decode_ifd(data, primary)
    assert width == WIDTH and height == HEIGHT
    return grid


def tie_point_origin(tags: dict[int, object]) -> tuple[int, int]:
    """Return the (x, y) map coordinate of the upper-left pixel corner from ModelTiepointTag."""
    tie = tags.get(33922)
    if not isinstance(tie, list) or len(tie) < 6 or tie[0] != 0 or tie[1] != 0:
        raise CogError(f"unexpected ModelTiepoint {tie!r}")
    return int(round(tie[3])), int(round(tie[4]))


def main(argv: list[str]) -> int:
    """--check-headers SOURCES.tsv RASTER_DIR: validate every pinned local COG."""
    import csv
    import os
    if len(argv) != 3 or argv[0] != "--check-headers":
        print("usage: cdl_cog.py --check-headers SOURCES.tsv RASTER_DIR", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    for row in rows:
        path = os.path.join(argv[2], os.path.basename(row["url"]))
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            primary = check_file(data)
            x0, y0 = tie_point_origin(primary)
        except CogError as exc:
            print(f"FATAL: {row['item_id']}: {exc}", file=sys.stderr)
            return 1
        # item id cropland_2021_<x>_<y>_90000 encodes the tile's map origin
        # (x = left edge, y = top edge - 30 m in EPSG:5070); see proj:transform in STAC.
        parts = row["item_id"].split("_")
        if parts[:2] != ["cropland", "2021"] or parts[-1] != "90000":
            print(f"FATAL: unexpected item id {row['item_id']}", file=sys.stderr)
            return 1
        if (int(parts[2]), int(parts[3]) + 30) != (x0, y0):
            print(f"FATAL: {row['item_id']}: GeoTIFF origin {x0},{y0} does not match item id", file=sys.stderr)
            return 1
        print(f"header_ok item={row['item_id']} origin={x0},{y0} ifds=1+{len(parse_ifds(data)) - 1}")
    print(f"headers_ok files={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
