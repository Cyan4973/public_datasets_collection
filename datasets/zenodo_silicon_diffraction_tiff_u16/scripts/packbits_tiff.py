#!/usr/bin/env python3
"""Decode and characterize the pinned uint16 PackBits EBSD TIFF."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import struct
import sys


EXPECTED_SIZE = 3_715_496
EXPECTED_MD5 = "fb93782184b1b324eed85c1e377cc505"
WIDTH = 1_600
HEIGHT = 1_152
ROWS_PER_STRIP = 18
STRIP_COUNT = 64
VALUE_COUNT = WIDTH * HEIGHT
OUTPUT_BYTES = VALUE_COUNT * 2
TYPE_SIZES = {1: 1, 3: 2, 4: 4}


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_values(data: bytes, endian: str, field_offset: int, value_type: int, count: int) -> list[int]:
    if value_type not in TYPE_SIZES or count <= 0:
        raise ValueError(f"unsupported TIFF value type/count {value_type}/{count}")
    byte_count = TYPE_SIZES[value_type] * count
    start = field_offset if byte_count <= 4 else struct.unpack_from(endian + "I", data, field_offset)[0]
    if start < 0 or start + byte_count > len(data):
        raise ValueError("TIFF tag values exceed file bounds")
    fmt = {1: "B", 3: "H", 4: "I"}[value_type]
    return list(struct.unpack_from(endian + str(count) + fmt, data, start))


def parse_layout(data: bytes) -> dict[str, object]:
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        raise ValueError("invalid TIFF byte-order marker")
    if endian != "<" or struct.unpack_from("<H", data, 2)[0] != 42:
        raise ValueError("expected little-endian standard TIFF")
    ifd_offset = struct.unpack_from("<I", data, 4)[0]
    if ifd_offset + 2 > len(data):
        raise ValueError("TIFF IFD exceeds file bounds")
    entry_count = struct.unpack_from("<H", data, ifd_offset)[0]
    if ifd_offset + 2 + entry_count * 12 + 4 > len(data):
        raise ValueError("truncated TIFF IFD")
    tags: dict[int, list[int]] = {}
    for index in range(entry_count):
        offset = ifd_offset + 2 + index * 12
        tag, value_type = struct.unpack_from("<HH", data, offset)
        count = struct.unpack_from("<I", data, offset + 4)[0]
        if tag in {256, 257, 258, 259, 262, 273, 274, 277, 278, 279, 284, 317, 339}:
            tags[tag] = read_values(data, "<", offset + 8, value_type, count)
    def one(tag: int, default: int | None = None) -> int:
        values = tags.get(tag)
        if values is None:
            if default is None:
                raise ValueError(f"missing TIFF tag {tag}")
            return default
        if len(values) != 1:
            raise ValueError(f"TIFF tag {tag} is not scalar")
        return values[0]
    expected = {
        256: WIDTH,
        257: HEIGHT,
        258: 16,
        259: 32773,
        274: 1,
        277: 1,
        278: ROWS_PER_STRIP,
        284: 1,
        317: 1,
        339: 1,
    }
    for tag, value in expected.items():
        if one(tag, value) != value:
            raise ValueError(f"unexpected TIFF tag {tag}: {one(tag, value)} != {value}")
    offsets = tags.get(273, [])
    byte_counts = tags.get(279, [])
    if len(offsets) != STRIP_COUNT or len(byte_counts) != STRIP_COUNT:
        raise ValueError("unexpected TIFF strip count")
    if any(offset + count > len(data) for offset, count in zip(offsets, byte_counts)):
        raise ValueError("TIFF strip exceeds file bounds")
    return {
        "ifd_offset": ifd_offset,
        "strip_offsets": offsets,
        "strip_byte_counts": byte_counts,
        "compressed_strip_bytes": sum(byte_counts),
    }


def decode_packbits(data: bytes) -> bytes:
    output = bytearray()
    offset = 0
    while offset < len(data):
        control = data[offset]
        offset += 1
        if control <= 127:
            count = control + 1
            if offset + count > len(data):
                raise ValueError("truncated PackBits literal run")
            output.extend(data[offset : offset + count])
            offset += count
        elif control >= 129:
            count = 257 - control
            if offset >= len(data):
                raise ValueError("truncated PackBits repeated run")
            output.extend([data[offset]] * count)
            offset += 1
        # 128 is a no-op.
    return bytes(output)


def decode_image(path: Path) -> tuple[bytes, dict[str, object]]:
    if path.stat().st_size != EXPECTED_SIZE or md5(path) != EXPECTED_MD5:
        raise ValueError("source TIFF size or MD5 mismatch")
    data = path.read_bytes()
    layout = parse_layout(data)
    output = bytearray()
    offsets = layout["strip_offsets"]
    byte_counts = layout["strip_byte_counts"]
    decoded_strip_bytes: list[int] = []
    for strip_index, (offset, byte_count) in enumerate(zip(offsets, byte_counts)):
        decoded = decode_packbits(data[offset : offset + byte_count])
        rows = min(ROWS_PER_STRIP, HEIGHT - strip_index * ROWS_PER_STRIP)
        expected = rows * WIDTH * 2
        if len(decoded) != expected:
            raise ValueError(f"strip {strip_index} decoded to {len(decoded)} bytes, expected {expected}")
        decoded_strip_bytes.append(len(decoded))
        output.extend(decoded)
    if len(output) != OUTPUT_BYTES:
        raise ValueError("decoded detector plane has an unexpected size")
    layout["decoded_strip_bytes"] = decoded_strip_bytes
    return bytes(output), layout


def inspect(path: Path) -> dict[str, object]:
    payload, layout = decode_image(path)
    values = array("H")
    values.frombytes(payload)
    if values.itemsize != 2:
        raise ValueError("host unsigned-short width is not 16 bits")
    if sys.byteorder == "big":
        values.byteswap()
    distinct = set(values)
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    return {
        "source_file": path.name,
        "source_bytes": path.stat().st_size,
        "source_md5": EXPECTED_MD5,
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "compression": "packbits",
        "width": WIDTH,
        "height": HEIGHT,
        "value_count": VALUE_COUNT,
        "decoded_bytes": len(payload),
        "minimum": min(values),
        "maximum": max(values),
        "distinct_values": len(distinct),
        "zero_values": values.count(0),
        "zero_fraction": values.count(0) / VALUE_COUNT,
        "saturated_values": values.count(65535),
        "mean": sum(values) / VALUE_COUNT,
        "flattened_transitions": transitions,
        "decoded_sha256": hashlib.sha256(payload).hexdigest(),
        **layout,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--tiff", type=Path, required=True)
    inspect_parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.tiff.is_file():
        raise SystemExit(f"missing TIFF source: {args.tiff}")
    report = inspect(args.tiff)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key not in {"strip_offsets", "strip_byte_counts", "decoded_strip_bytes"}}
    print(json.dumps(summary, indent=2, sort_keys=True))
    if int(report["distinct_values"]) < 256:
        raise SystemExit("too few distinct diffraction detector values")
    if float(report["zero_fraction"]) > 0.99:
        raise SystemExit("diffraction image is overwhelmingly zero")


if __name__ == "__main__":
    main()
