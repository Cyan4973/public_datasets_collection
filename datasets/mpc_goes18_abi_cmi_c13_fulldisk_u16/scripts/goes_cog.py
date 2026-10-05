#!/usr/bin/env python3
"""Pure-stdlib reader for the Planetary Computer GOES ABI CMI band COGs.

The Microsoft Planetary Computer `goes-cmi` collection exports each band of
NOAA's OR_ABI-L2-MCMIPF NetCDF product as a classic little-endian
Cloud-Optimized GeoTIFF: one primary IFD (the full 5424x5424 2 km grid) plus
four overview IFDs.  The primary IFD stores the packed NetCDF variable
`CMI_C13` (uint16 codes, `_Unsigned=true`) in 512x512 Deflate tiles without a
predictor.  This module validates that exact structure and rebuilds the
primary grid in row-major order.  Overviews are validated for presence only
and never decoded.

Usage (from download.sh):
    goes_cog.py validate <cog.tif> <expected_source_netcdf_name>
"""
from __future__ import annotations

import json
import math
import re
import struct
import sys
import zlib

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q"}

TAG_NAMES = {
    256: "width",
    257: "height",
    258: "bits_per_sample",
    259: "compression",
    262: "photometric",
    277: "samples_per_pixel",
    284: "planar_configuration",
    317: "predictor",
    322: "tile_width",
    323: "tile_height",
    339: "sample_format",
}

# Exact primary-IFD structure required for this recipe.
EXPECTED_PRIMARY = {
    "width": 5424,
    "height": 5424,
    "bits_per_sample": 16,
    "compression": 8,
    "photometric": 1,
    "samples_per_pixel": 1,
    "planar_configuration": 1,
    "predictor": 1,
    "tile_width": 512,
    "tile_height": 512,
    "sample_format": 1,
}
EXPECTED_IFD_COUNT = 5  # primary + 2712, 1356, 678, 339 overviews
EXPECTED_NODATA = "65535"
EXPECTED_METADATA = {
    "band:NETCDF_VARNAME": "CMI_C13",
    "CMI_C13#scale_factor": "0.06145332",
    "CMI_C13#add_offset": "89.620003",
    "CMI_C13#units": "K",
    "CMI_C13#valid_range": "{0,4095}",
    "CMI_C13#sensor_band_bit_depth": "12",
    "CMI_C13#standard_name": "toa_brightness_temperature",
    "CMI_C13#_Unsigned": "true",
    "band:_FillValue": "65535",
    "NC_GLOBAL#platform_ID": "G18",
    "NC_GLOBAL#scene_id": "Full Disk",
    "NC_GLOBAL#timeline_id": "ABI Mode 6",
    "NC_GLOBAL#orbital_slot": "GOES-West",
    "NC_GLOBAL#title": "ABI L2 Cloud and Moisture Imagery",
    "goes_imager_projection#longitude_of_projection_origin": "-137",
}


class CogError(ValueError):
    pass


def _entry_value(data: bytes, endian: str, field_type: int, count: int, raw: bytes):
    size = TYPE_SIZE.get(field_type)
    if size is None:
        raise CogError(f"unsupported TIFF field type {field_type}")
    nbytes = size * count
    if nbytes <= 4:
        blob = raw[:nbytes]
    else:
        offset = struct.unpack(endian + "I", raw)[0]
        if offset + nbytes > len(data):
            raise CogError(f"TIFF value outside file offset={offset} bytes={nbytes}")
        blob = data[offset:offset + nbytes]
    if field_type == 2:
        return blob.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    fmt = TYPE_FMT.get(field_type)
    if fmt is None:
        return blob
    return list(struct.unpack(endian + fmt * count, blob))


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
            tags[tag] = _entry_value(data, "<", field_type, n, data[pos + 8:pos + 12])
        ifds.append(tags)
        offset = struct.unpack_from("<I", data, end)[0]
        if len(ifds) > 64:
            raise CogError("too many IFDs")
    return ifds


def _scalar(tags: dict[int, object], tag: int, default: int | None = None) -> int:
    value = tags.get(tag)
    if isinstance(value, list) and value:
        return int(value[0])
    if default is not None:
        return default
    raise CogError(f"missing TIFF tag {tag}")


def gdal_metadata(tags: dict[int, object]) -> dict[str, str]:
    xml = tags.get(42112)
    if not isinstance(xml, str) or "<GDALMetadata>" not in xml:
        raise CogError("missing GDAL_METADATA tag 42112")
    items: dict[str, str] = {}
    for match in re.finditer(r'<Item name="([^"]+)"((?:\s+\w+="[^"]*")*)>([^<]*)</Item>', xml):
        name, attrs, value = match.group(1), match.group(2), match.group(3)
        key = f"band:{name}" if 'sample="0"' in attrs and "#" not in name else name
        items[key] = value.strip()
    return items


def primary_structure(data: bytes, expected: dict[str, int] | None = None, ifd_count: int | None = None) -> dict:
    """Validate the primary IFD and return its structure plus tile tables."""
    expected = EXPECTED_PRIMARY if expected is None else expected
    ifds = parse_ifds(data)
    if ifd_count is not None and len(ifds) != ifd_count:
        raise CogError(f"expected {ifd_count} IFDs, found {len(ifds)}")
    tags = ifds[0]
    if 254 in tags and _scalar(tags, 254) != 0:
        raise CogError("first IFD is not the full-resolution image")
    actual = {name: _scalar(tags, tag, 1 if tag in (259, 277, 284, 317, 339) else None) for tag, name in TAG_NAMES.items()}
    if actual != expected:
        diff = {k: (actual.get(k), v) for k, v in expected.items() if actual.get(k) != v}
        raise CogError(f"unexpected primary TIFF structure (actual, expected): {diff}")
    offsets = tags.get(324)
    counts = tags.get(325)
    across = math.ceil(actual["width"] / actual["tile_width"])
    down = math.ceil(actual["height"] / actual["tile_height"])
    if not isinstance(offsets, list) or not isinstance(counts, list):
        raise CogError("missing TileOffsets/TileByteCounts")
    if len(offsets) != across * down or len(counts) != across * down:
        raise CogError(f"tile table sizes {len(offsets)}/{len(counts)} != {across * down}")
    for index, (off, cnt) in enumerate(zip(offsets, counts)):
        if cnt <= 0 or off <= 0 or off + cnt > len(data):
            raise CogError(f"tile {index} range outside file offset={off} bytes={cnt}")
    for level, ifd in enumerate(ifds[1:], 1):
        if _scalar(ifd, 254, 0) != 1:
            raise CogError(f"IFD {level} is not a reduced-resolution overview")
    nodata = tags.get(42113)
    return {
        **actual,
        "ifd_count": len(ifds),
        "tiles_across": across,
        "tiles_down": down,
        "tile_offsets": offsets,
        "tile_byte_counts": counts,
        "gdal_nodata": nodata.strip() if isinstance(nodata, str) else None,
        "tags": tags,
    }


def validate(data: bytes, expected_netcdf: str | None) -> dict:
    """Full recipe-level validation of one CMI_C13 COG (header only, no decode)."""
    info = primary_structure(data, EXPECTED_PRIMARY, EXPECTED_IFD_COUNT)
    if info["gdal_nodata"] != EXPECTED_NODATA:
        raise CogError(f"GDAL_NODATA {info['gdal_nodata']!r} != {EXPECTED_NODATA!r}")
    meta = gdal_metadata(info["tags"])
    for key, value in EXPECTED_METADATA.items():
        if meta.get(key) != value:
            raise CogError(f"GDAL metadata {key}={meta.get(key)!r}, expected {value!r}")
    if expected_netcdf is not None and meta.get("NC_GLOBAL#dataset_name") != expected_netcdf:
        raise CogError(f"source NetCDF {meta.get('NC_GLOBAL#dataset_name')!r} != pinned {expected_netcdf!r}")
    return {
        "structure": {k: v for k, v in info.items() if k not in ("tags", "tile_offsets", "tile_byte_counts")},
        "metadata": {
            "source_netcdf": meta.get("NC_GLOBAL#dataset_name"),
            "time_coverage_start": meta.get("NC_GLOBAL#time_coverage_start"),
            "time_coverage_end": meta.get("NC_GLOBAL#time_coverage_end"),
            "netcdf_variable": meta.get("band:NETCDF_VARNAME"),
            "scale_factor": meta.get("CMI_C13#scale_factor"),
            "add_offset": meta.get("CMI_C13#add_offset"),
            "units": meta.get("CMI_C13#units"),
            "valid_range": meta.get("CMI_C13#valid_range"),
            "fill_value": meta.get("band:_FillValue"),
            "sensor_band_bit_depth": meta.get("CMI_C13#sensor_band_bit_depth"),
            "instrument_id": meta.get("NC_GLOBAL#instrument_ID"),
            "production_site": meta.get("NC_GLOBAL#production_site"),
        },
    }


def decode_primary(data: bytes, expected: dict[str, int] | None = None, ifd_count: int | None = None) -> bytes:
    """Rebuild the primary grid as row-major little-endian 16-bit samples.

    Every Deflate tile must inflate to exactly tile_width*tile_height*2 bytes;
    right/bottom edge tiles are cropped to the image extent (the padding
    outside the image is discarded).
    """
    info = primary_structure(data, expected, ifd_count)
    width, height = info["width"], info["height"]
    tw, th = info["tile_width"], info["tile_height"]
    bps = info["bits_per_sample"] // 8
    across = info["tiles_across"]
    tile_bytes = tw * th * bps
    row_bytes = width * bps
    out = bytearray(width * height * bps)
    for index, (off, cnt) in enumerate(zip(info["tile_offsets"], info["tile_byte_counts"])):
        payload = data[off:off + cnt]
        try:
            tile = zlib.decompress(payload)
        except zlib.error as exc:
            raise CogError(f"tile {index}: deflate error {exc}") from exc
        if len(tile) != tile_bytes:
            raise CogError(f"tile {index}: inflated {len(tile)} bytes, expected {tile_bytes}")
        tx, ty = index % across, index // across
        copy_w = min(tw, width - tx * tw) * bps
        copy_h = min(th, height - ty * th)
        for r in range(copy_h):
            src = r * tw * bps
            dst = (ty * th + r) * row_bytes + tx * tw * bps
            out[dst:dst + copy_w] = tile[src:src + copy_w]
    return bytes(out)


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] != "validate":
        print(__doc__, file=sys.stderr)
        return 2
    path, expected_netcdf = argv[2], argv[3]
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        report = validate(data, expected_netcdf)
    except CogError as exc:
        print(f"INVALID {path}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
