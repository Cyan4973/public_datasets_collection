#!/usr/bin/env python3
"""Minimal TIFF/BigTIFF metadata parser for the accepted AlphaEarth COG recipe."""

from __future__ import annotations

import math
from pathlib import Path
import struct
from typing import Any


TYPE_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    6: 1,
    7: 1,
    8: 2,
    9: 4,
    10: 8,
    11: 4,
    12: 8,
    16: 8,
    17: 8,
    18: 8,
}
TYPE_FORMATS = {
    1: "B",
    3: "H",
    4: "I",
    6: "b",
    8: "h",
    9: "i",
    11: "f",
    12: "d",
    16: "Q",
    17: "q",
    18: "Q",
}


def parse_header(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if data[:2] == b"II":
        endian = "<"
        byte_order = "little"
    elif data[:2] == b"MM":
        endian = ">"
        byte_order = "big"
    else:
        raise ValueError(f"{path}: not a TIFF file")

    magic = struct.unpack_from(endian + "H", data, 2)[0]
    if magic == 42:
        bigtiff = False
        ifd_offset = struct.unpack_from(endian + "I", data, 4)[0]
        count_fmt, count_size, entry_size, inline_size, offset_fmt = "H", 2, 12, 4, "I"
    elif magic == 43:
        bigtiff = True
        offset_size, reserved = struct.unpack_from(endian + "HH", data, 4)
        if offset_size != 8 or reserved != 0:
            raise ValueError(f"{path}: unsupported BigTIFF header")
        ifd_offset = struct.unpack_from(endian + "Q", data, 8)[0]
        count_fmt, count_size, entry_size, inline_size, offset_fmt = "Q", 8, 20, 8, "Q"
    else:
        raise ValueError(f"{path}: unsupported TIFF magic {magic}")

    def span(offset: int, size: int, label: str) -> bytes:
        if offset < 0 or size < 0 or offset + size > len(data):
            raise ValueError(
                f"{path}: {label} outside fetched header: offset={offset} "
                f"size={size} fetched={len(data)}"
            )
        return data[offset : offset + size]

    span(ifd_offset, count_size, "IFD count")
    entry_count = struct.unpack_from(endian + count_fmt, data, ifd_offset)[0]
    tags: dict[int, tuple[int, int, bytes]] = {}
    for index in range(entry_count):
        offset = ifd_offset + count_size + index * entry_size
        raw = span(offset, entry_size, f"IFD entry {index}")
        if bigtiff:
            tag, field_type, count = struct.unpack_from(endian + "HHQ", raw, 0)
            inline = raw[12:20]
        else:
            tag, field_type, count = struct.unpack_from(endian + "HHI", raw, 0)
            inline = raw[8:12]
        tags[tag] = (field_type, count, inline)

    def values(tag: int) -> list[int | float]:
        if tag not in tags:
            return []
        field_type, count, inline = tags[tag]
        item_size = TYPE_SIZES.get(field_type)
        fmt = TYPE_FORMATS.get(field_type)
        if item_size is None or fmt is None:
            return []
        size = item_size * count
        if size <= inline_size:
            raw = inline[:size]
        else:
            value_offset = struct.unpack(endian + offset_fmt, inline)[0]
            raw = span(value_offset, size, f"tag {tag}")
        return list(struct.unpack(endian + fmt * count, raw))

    def scalar(tag: int, default: int | None = None) -> int | None:
        found = values(tag)
        return int(found[0]) if found else default

    width = scalar(256)
    height = scalar(257)
    tile_width = scalar(322)
    tile_length = scalar(323)
    samples_per_pixel = scalar(277, 1)
    if None in (width, height, tile_width, tile_length, samples_per_pixel):
        raise ValueError(f"{path}: required TIFF geometry tags are absent")
    tile_offsets = [int(value) for value in values(324)]
    tile_byte_counts = [int(value) for value in values(325)]
    model_pixel_scale = [float(value) for value in values(33550)]
    model_tiepoints = [float(value) for value in values(33922)]
    model_transformation = [float(value) for value in values(34264)]
    geokey_directory = [int(value) for value in values(34735)]
    projected_crs_epsg = None
    if len(geokey_directory) >= 4:
        key_count = geokey_directory[3]
        if len(geokey_directory) >= 4 + key_count * 4:
            for index in range(key_count):
                key_id, tag_location, count, value_offset = geokey_directory[4 + index * 4 : 8 + index * 4]
                if key_id == 3072 and tag_location == 0 and count == 1:
                    projected_crs_epsg = value_offset
    result = {
        "byte_order": byte_order,
        "bigtiff": bigtiff,
        "ifd_offset": ifd_offset,
        "ifd_entry_count": entry_count,
        "width": width,
        "height": height,
        "bits_per_sample": [int(value) for value in values(258)],
        "compression": scalar(259, 1),
        "photometric_interpretation": scalar(262),
        "samples_per_pixel": samples_per_pixel,
        "planar_configuration": scalar(284, 1),
        "predictor": scalar(317, 1),
        "tile_width": tile_width,
        "tile_length": tile_length,
        "sample_formats": [int(value) for value in values(339)] or [1],
        "tile_offsets": tile_offsets,
        "tile_byte_counts": tile_byte_counts,
        "tiles_across": math.ceil(width / tile_width),
        "tiles_down": math.ceil(height / tile_length),
        "model_pixel_scale": model_pixel_scale,
        "model_tiepoints": model_tiepoints,
        "model_transformation": model_transformation,
        "projected_crs_epsg": projected_crs_epsg,
    }
    return result


def validate_alphaearth(info: dict[str, Any], label: str) -> None:
    expected_scalars = {
        "byte_order": "little",
        "bigtiff": True,
        "width": 8192,
        "height": 8192,
        "compression": 50000,
        "samples_per_pixel": 64,
        "planar_configuration": 2,
        "predictor": 1,
        "tile_width": 1024,
        "tile_length": 1024,
        "tiles_across": 8,
        "tiles_down": 8,
    }
    for key, expected in expected_scalars.items():
        if info.get(key) != expected:
            raise ValueError(f"{label}: unexpected {key}={info.get(key)!r}, expected {expected!r}")
    bits = info["bits_per_sample"]
    formats = info["sample_formats"]
    if not bits or set(bits) != {8}:
        raise ValueError(f"{label}: expected 8-bit samples, found {bits}")
    if not formats or set(formats) != {2}:
        raise ValueError(f"{label}: expected signed-integer SampleFormat=2, found {formats}")
    offsets = info["tile_offsets"]
    counts = info["tile_byte_counts"]
    expected_chunks = 64 * 8 * 8
    if len(offsets) != expected_chunks or len(counts) != expected_chunks:
        raise ValueError(
            f"{label}: expected {expected_chunks} planar tile chunks, "
            f"found offsets={len(offsets)} counts={len(counts)}"
        )
    if any(offset < 0 for offset in offsets) or any(count <= 0 for count in counts):
        raise ValueError(f"{label}: invalid tile offset or byte count")
    scale = info["model_pixel_scale"]
    transform = info["model_transformation"]
    scale_is_10m = len(scale) >= 2 and scale[:2] == [10.0, 10.0]
    transform_is_10m = (
        len(transform) == 16
        and abs(abs(transform[0]) - 10.0) < 1e-9
        and abs(abs(transform[5]) - 10.0) < 1e-9
    )
    if not scale_is_10m and not transform_is_10m:
        raise ValueError(
            f"{label}: expected 10 m square pixels, "
            f"found scale={scale} transformation={transform}"
        )
    epsg = info["projected_crs_epsg"]
    if not isinstance(epsg, int) or not (32601 <= epsg <= 32660 or 32701 <= epsg <= 32760):
        raise ValueError(f"{label}: expected WGS 84 UTM projected CRS, found EPSG:{epsg}")


def chunk_index(axis: int, spatial_index: int) -> int:
    if not 0 <= axis < 64 or not 0 <= spatial_index < 64:
        raise ValueError(f"invalid AlphaEarth tile coordinates: axis={axis} spatial={spatial_index}")
    return axis * 64 + spatial_index
