#!/usr/bin/env python3
"""Strict pure-stdlib reader for Planetary Computer MOD15A2H.061 Fpar_500m COGs.

Used by download.sh (header validation) and build.sh (primary-grid decode).
verify.sh deliberately uses its own independent decoder.

The files are little-endian classic TIFFs: IFD0 is the 2400x2400 primary
grid (uint8, SampleFormat 1, Deflate, predictor 1, 512x512 tiles, GDAL nodata
255) followed by three reduced-resolution overview IFDs (1200, 600, 300)
that the recipe ignores.
"""
from __future__ import annotations

import re
import struct
import sys
import zlib

WIDTH = 2400
HEIGHT = 2400
TILE = 512
VALID_MIN = 0
VALID_MAX = 100
FILL_CLASSES = tuple(range(248, 256))  # source-native fill/land-cover classes, kept as stored
NODATA = 255
OVERVIEW_SIZES = [1200, 600, 300]
LONG_NAME = "MOD15A2H MODIS/Terra Gridded 500M FPAR (8-day composite)"

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d"}

EXPECTED_PRIMARY = {
    256: WIDTH,   # ImageWidth
    257: HEIGHT,  # ImageLength
    258: 8,       # BitsPerSample
    259: 8,       # Compression: Adobe Deflate
    262: 1,       # Photometric: BlackIsZero
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


def parse_ifds(data: bytes) -> list[dict[int, object]]:
    """Parse every IFD of a little-endian classic TIFF into {tag: values}."""
    if len(data) < 8 or data[:4] != b"II*\x00":
        raise CogError("not a little-endian classic TIFF")
    offset = struct.unpack_from("<I", data, 4)[0]
    ifds: list[dict[int, object]] = []
    seen: set[int] = set()
    while offset:
        if offset in seen or offset + 2 > len(data):
            raise CogError(f"invalid IFD offset {offset}")
        seen.add(offset)
        count = struct.unpack_from("<H", data, offset)[0]
        end = offset + 2 + 12 * count
        if end + 4 > len(data):
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


def gdal_items(tags: dict[int, object]) -> dict[str, str]:
    """Dataset-level GDAL metadata items (first occurrence wins; band-role items included)."""
    text = tags.get(42112)
    if not isinstance(text, str):
        raise CogError("missing GDAL_METADATA tag 42112")
    items: dict[str, str] = {}
    for name, value in re.findall(r'<Item name="([^"]+)"(?: [^>]*)?>([^<]*)</Item>', text):
        items.setdefault(name, value)
    return items


def expected_metadata(item_id: str, tile: str, start_date: str, end_date: str) -> dict[str, str]:
    h, v = tile[1:3], tile[4:6]
    return {
        "SHORTNAME": "MOD15A2H",
        "VERSIONID": "61",
        "ASSOCIATEDPLATFORMSHORTNAME.1": "Terra",
        "LOCALGRANULEID": f"{item_id}.hdf",
        "HORIZONTALTILENUMBER": h,
        "VERTICALTILENUMBER": v,
        "RANGEBEGINNINGDATE": start_date,
        "RANGEENDINGDATE": end_date,
        "identifier_product_doi": "10.5067/MODIS/MOD15A2H.061",
        "long_name": LONG_NAME,
        "units": "Percent",
        "_FillValue": str(NODATA),
        "valid_range": f"{VALID_MIN}, {VALID_MAX}",
        "scale_factor": "0.01",
        "add_offset": "0",
        "DATACOLUMNS500M": str(WIDTH),
        "DATAROWS500M": str(HEIGHT),
    }


def check_structure(data: bytes, item_id: str, tile: str, start_date: str, end_date: str) -> dict[int, object]:
    """Reject anything that is not the pinned MOD15A2H.061 Terra Fpar_500m tile."""
    ifds = parse_ifds(data)
    if len(ifds) != 1 + len(OVERVIEW_SIZES):
        raise CogError(f"expected primary IFD plus {len(OVERVIEW_SIZES)} overviews, found {len(ifds)} IFDs")
    primary = ifds[0]
    actual = {tag: scalar(primary, tag) for tag in EXPECTED_PRIMARY}
    if actual != EXPECTED_PRIMARY:
        raise CogError(f"unexpected primary TIFF structure {actual}")
    if primary.get(254) not in (None, [0]):
        raise CogError("IFD0 is flagged as a reduced-resolution image")
    if str(primary.get(42113, "")).strip() != str(NODATA):
        raise CogError(f"GDAL nodata is {primary.get(42113)!r}, expected {NODATA}")
    for overview, size in zip(ifds[1:], OVERVIEW_SIZES):
        if scalar(overview, 254) != 1 or scalar(overview, 256) != size or scalar(overview, 257) != size:
            raise CogError("unexpected overview IFD geometry")
        for off, n in zip(overview.get(324, []), overview.get(325, [])):
            if off <= 0 or n <= 0 or off + n > len(data):
                raise CogError(f"overview tile range outside file offset={off} bytes={n}")
    tiles = (WIDTH + TILE - 1) // TILE * ((HEIGHT + TILE - 1) // TILE)
    offsets, counts = primary.get(324), primary.get(325)
    if not isinstance(offsets, list) or not isinstance(counts, list) or len(offsets) != tiles or len(counts) != tiles:
        raise CogError("primary tile tables have the wrong length")
    for off, n in zip(offsets, counts):
        if off <= 0 or n <= 0 or off + n > len(data):
            raise CogError(f"tile range outside file offset={off} bytes={n}")
    meta = gdal_items(primary)
    expected = expected_metadata(item_id, tile, start_date, end_date)
    wrong = {k: (meta.get(k), want) for k, want in expected.items() if meta.get(k) != want}
    if wrong:
        raise CogError(f"GDAL metadata mismatch {wrong}")
    # NDAYS_COMPOSITED is the number of daily MOD15A1H inputs that entered the
    # 8-day composite (5..8 observed in the pinned files), not a product constant.
    ndays = meta.get("NDAYS_COMPOSITED", "")
    if not ndays.isdigit() or not 1 <= int(ndays) <= 8:
        raise CogError(f"NDAYS_COMPOSITED {ndays!r} outside 1..8")
    return primary


def granule_metadata(data: bytes) -> dict[str, str]:
    """GDAL metadata items of IFD0 (for provenance fields in the index)."""
    return gdal_items(parse_ifds(data)[0])


def inflate_exact(payload: bytes, expected: int) -> bytes:
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(payload)
        raw += inflater.flush()
    except zlib.error as exc:
        raise CogError(f"corrupt Deflate tile stream: {exc}") from exc
    if not inflater.eof:
        raise CogError("truncated Deflate tile stream")
    if inflater.unused_data:
        raise CogError(f"{len(inflater.unused_data)} unexpected bytes after Deflate tile stream")
    if len(raw) != expected:
        raise CogError(f"decoded tile bytes={len(raw)} expected={expected}")
    return raw


def assemble_tiles(data: bytes, width: int, height: int, tile_w: int, tile_h: int,
                   offsets: list[int], counts: list[int], element: int = 1) -> bytes:
    """Inflate every tile and crop TIFF edge padding into a row-major grid."""
    across = (width + tile_w - 1) // tile_w
    down = (height + tile_h - 1) // tile_h
    if len(offsets) != across * down or len(counts) != across * down:
        raise CogError("tile table length mismatch")
    out = bytearray(width * height * element)
    row_bytes = width * element
    tile_row_bytes = tile_w * element
    for index, (off, n) in enumerate(zip(offsets, counts)):
        tile = inflate_exact(data[off:off + n], tile_w * tile_h * element)
        tx, ty = index % across, index // across
        copy_w = min(tile_w, width - tx * tile_w) * element
        copy_h = min(tile_h, height - ty * tile_h)
        for row in range(copy_h):
            src = row * tile_row_bytes
            dst = (ty * tile_h + row) * row_bytes + tx * tile_w * element
            out[dst:dst + copy_w] = tile[src:src + copy_w]
    return bytes(out)


def decode_primary(data: bytes, item_id: str, tile: str, start_date: str, end_date: str) -> bytes:
    primary = check_structure(data, item_id, tile, start_date, end_date)
    return assemble_tiles(data, WIDTH, HEIGHT, TILE, TILE, list(primary[324]), list(primary[325]))


def main(argv: list[str]) -> int:
    """Header check mode: mod15a2h_cog.py --check-headers PLAN.tsv RASTER_DIR."""
    if len(argv) != 4 or argv[1] != "--check-headers":
        print(main.__doc__, file=sys.stderr)
        return 2
    import csv
    from pathlib import Path
    plan, raster_dir = Path(argv[2]), Path(argv[3])
    with plan.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    for row in rows:
        path = raster_dir / f"{row['item_id']}_Fpar_500m.tif"
        data = path.read_bytes()
        try:
            check_structure(data, row["item_id"], row["tile"], row["start_date"], row["end_date"])
        except CogError as exc:
            print(f"FATAL: header check failed item={row['item_id']}: {exc}", file=sys.stderr)
            return 1
        print(f"header_ok item={row['item_id']} tile={row['tile']} doy={row['day_of_year']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
