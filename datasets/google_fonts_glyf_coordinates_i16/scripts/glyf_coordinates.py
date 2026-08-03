#!/usr/bin/env python3
"""Strictly decode simple-glyph TrueType coordinates to little-endian int16."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys


DATASET_ID = "google_fonts_glyf_coordinates_i16"
SERIES_ID = "truetype_simple_glyph_coordinates_i16"
COMMIT = "2796410152d4f9524b68ed46e69c1b60f8e0f7c3"
LICENSE_BYTES = 11_358
LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
SOURCES = (
    {
        "family": "aclonica",
        "name": "aclonica__Aclonica-Regular.ttf",
        "size": 68_732,
        "sha256": "774a49351cc62a469b56972e9769679ce818a3de15b409ad5f1b6244ee84d85b",
        "blob_sha": "bbe191d026edc985b049f313f7d3f60a76713a49",
        "glyph_count": 371,
        "simple_glyphs": 203,
        "composite_glyphs": 163,
        "empty_glyphs": 5,
        "simple_contours": 315,
        "simple_points": 7_317,
        "coordinate_values": 14_634,
        "minimum": -607,
        "maximum": 2_304,
        "distinct_values": 1_892,
        "transitions": 14_627,
        "boundaries_sha256": "f828204202c1ad08df0253e93f96989ed37d3c71fd141168bb6f75462247653e",
        "payload_sha256": "0b490c2ea90505d6f5ebdc351f36aabeaf0ec27a5a725d134185b201355c0352",
    },
    {
        "family": "robotoslab",
        "name": "robotoslab__RobotoSlab_wght_.ttf",
        "size": 251_880,
        "sha256": "786ae192477447d33c6672c3055fba7cbfe45184c9a79e77a14f15716ca05b16",
        "blob_sha": "1c46b300eda3677f604575ede4cd80f0d139c3be",
        "glyph_count": 1_164,
        "simple_glyphs": 483,
        "composite_glyphs": 665,
        "empty_glyphs": 16,
        "simple_contours": 782,
        "simple_points": 15_475,
        "coordinate_values": 30_950,
        "minimum": -555,
        "maximum": 2_408,
        "distinct_values": 2_080,
        "transitions": 30_942,
        "boundaries_sha256": "56a3f71e502c499345c3ce98f8fedd950ca9f8702ba0aad8f518400031285194",
        "payload_sha256": "254273ad1dc38dafa1ec97d22542fa3c9c27081283c5f01d2a6f4a2ab3d8a781",
    },
    {
        "family": "specialelite",
        "name": "specialelite__SpecialElite-Regular.ttf",
        "size": 166_180,
        "sha256": "a776fcb4ceb8bdf03e2967688ebdad42680de5b91a7e62c17e718ae212d14bc4",
        "blob_sha": "6654876f95f11cb2b55c7c4254727ef68dbea74c",
        "glyph_count": 370,
        "simple_glyphs": 202,
        "composite_glyphs": 163,
        "empty_glyphs": 5,
        "simple_contours": 410,
        "simple_points": 49_029,
        "coordinate_values": 98_058,
        "minimum": -659,
        "maximum": 2_154,
        "distinct_values": 2_432,
        "transitions": 98_004,
        "boundaries_sha256": "16f7fe61af6f7a8fd1789ce924fe28e03da71a1e3c31f4eb3e72998bc6a5743c",
        "payload_sha256": "11c300d679026d1a27696bf0745c29ac975df23b937f53d1c99629a62296694d",
    },
)
AGGREGATE_SHA256 = "442c8aabdc2ea8eceeffcb837f32f1d952e976f55ed2335e37af9c4526d85e97"


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def i16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">h", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def parse_tables(data: bytes) -> dict[bytes, tuple[int, int, int]]:
    if len(data) < 12 or data[:4] not in {b"\x00\x01\x00\x00", b"true"}:
        raise ValueError("not a supported TrueType-flavored SFNT")
    table_count = u16(data, 4)
    if not 1 <= table_count <= 256 or 12 + table_count * 16 > len(data):
        raise ValueError("invalid SFNT table directory")
    tables = {}
    for index in range(table_count):
        position = 12 + index * 16
        tag = data[position : position + 4]
        checksum = u32(data, position + 4)
        offset = u32(data, position + 8)
        length = u32(data, position + 12)
        if tag in tables or offset + length > len(data):
            raise ValueError(f"duplicate or out-of-bounds SFNT table {tag!r}")
        tables[tag] = (offset, length, checksum)
    for required in (b"head", b"maxp", b"loca", b"glyf"):
        if required not in tables:
            raise ValueError(f"missing required TrueType table {required!r}")
    return tables


def decode_simple_glyph(glyph: bytes) -> tuple[list[tuple[int, int]], int]:
    if len(glyph) < 10:
        raise ValueError("truncated glyph header")
    contour_count = i16(glyph, 0)
    if contour_count < 0:
        raise ValueError("composite glyph passed to simple decoder")
    if contour_count == 0:
        return [], 0
    cursor = 10
    if cursor + contour_count * 2 + 2 > len(glyph):
        raise ValueError("truncated simple-glyph contour endpoints")
    endpoints = [u16(glyph, cursor + index * 2) for index in range(contour_count)]
    if endpoints != sorted(endpoints) or len(set(endpoints)) != len(endpoints):
        raise ValueError("simple-glyph contour endpoints are not strictly increasing")
    point_count = endpoints[-1] + 1
    cursor += contour_count * 2
    instruction_bytes = u16(glyph, cursor)
    cursor += 2 + instruction_bytes
    if cursor > len(glyph):
        raise ValueError("simple-glyph instructions exceed glyph bounds")
    flags = []
    while len(flags) < point_count:
        if cursor >= len(glyph):
            raise ValueError("truncated simple-glyph flags")
        flag = glyph[cursor]
        cursor += 1
        flags.append(flag)
        if flag & 0x08:
            if cursor >= len(glyph):
                raise ValueError("truncated simple-glyph flag repeat")
            repeat = glyph[cursor]
            cursor += 1
            flags.extend([flag] * repeat)
    if len(flags) != point_count:
        raise ValueError("simple-glyph flags exceed declared point count")

    def decode_axis(short_mask: int, same_mask: int) -> list[int]:
        nonlocal cursor
        coordinates = []
        current = 0
        for flag in flags:
            if flag & short_mask:
                if cursor >= len(glyph):
                    raise ValueError("truncated short glyph-coordinate delta")
                magnitude = glyph[cursor]
                cursor += 1
                delta = magnitude if flag & same_mask else -magnitude
            elif flag & same_mask:
                delta = 0
            else:
                if cursor + 2 > len(glyph):
                    raise ValueError("truncated signed glyph-coordinate delta")
                delta = i16(glyph, cursor)
                cursor += 2
            current += delta
            if not -32768 <= current <= 32767:
                raise ValueError("reconstructed glyph coordinate exceeds signed int16")
            coordinates.append(current)
        return coordinates

    xs = decode_axis(0x02, 0x10)
    ys = decode_axis(0x04, 0x20)
    points = list(zip(xs, ys))
    declared_bounds = tuple(i16(glyph, offset) for offset in (2, 4, 6, 8))
    observed_bounds = (min(xs), min(ys), max(xs), max(ys))
    if observed_bounds != declared_bounds:
        raise ValueError(f"glyph bounds mismatch: {observed_bounds} != {declared_bounds}")
    return points, contour_count


def decode_font(path: Path, expected: dict[str, object]) -> tuple[bytes, dict[str, object]]:
    if path.stat().st_size != expected["size"] or file_hash(path, "sha256") != expected["sha256"]:
        raise ValueError(f"{path.name}: source size or SHA-256 mismatch")
    data = path.read_bytes()
    blob_sha = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if blob_sha != expected["blob_sha"]:
        raise ValueError(f"{path.name}: Git blob SHA mismatch")
    tables = parse_tables(data)
    head_offset, head_length, _ = tables[b"head"]
    maxp_offset, maxp_length, _ = tables[b"maxp"]
    loca_offset, loca_length, _ = tables[b"loca"]
    glyf_offset, glyf_length, _ = tables[b"glyf"]
    if head_length < 54 or maxp_length < 6 or u32(data, head_offset + 12) != 0x5F0F3CF5:
        raise ValueError("truncated or invalid head/maxp table")
    units_per_em = u16(data, head_offset + 18)
    font_bounds = tuple(i16(data, head_offset + offset) for offset in (36, 38, 40, 42))
    loca_format = i16(data, head_offset + 50)
    glyph_count = u16(data, maxp_offset + 4)
    if loca_format == 0:
        if loca_length < (glyph_count + 1) * 2:
            raise ValueError("short loca table is truncated")
        glyph_offsets = [u16(data, loca_offset + index * 2) * 2 for index in range(glyph_count + 1)]
    elif loca_format == 1:
        if loca_length < (glyph_count + 1) * 4:
            raise ValueError("long loca table is truncated")
        glyph_offsets = [u32(data, loca_offset + index * 4) for index in range(glyph_count + 1)]
    else:
        raise ValueError(f"unsupported indexToLocFormat {loca_format}")
    if glyph_offsets != sorted(glyph_offsets) or glyph_offsets[-1] > glyf_length:
        raise ValueError("loca offsets are not monotonic or exceed glyf table")

    simple_glyphs = 0
    composite_glyphs = 0
    empty_glyphs = 0
    simple_contours = 0
    points: list[tuple[int, int]] = []
    boundary_digest = hashlib.sha256()
    for glyph_index in range(glyph_count):
        start, end = glyph_offsets[glyph_index], glyph_offsets[glyph_index + 1]
        if start == end:
            empty_glyphs += 1
            continue
        glyph = data[glyf_offset + start : glyf_offset + end]
        if len(glyph) < 10:
            raise ValueError(f"glyph {glyph_index} is truncated")
        declared_contours = i16(glyph, 0)
        if declared_contours == -1:
            composite_glyphs += 1
            continue
        if declared_contours < -1:
            raise ValueError(f"glyph {glyph_index} has invalid contour count {declared_contours}")
        glyph_points, contour_count = decode_simple_glyph(glyph)
        boundary_digest.update(struct.pack("<III", glyph_index, len(glyph_points), contour_count))
        simple_glyphs += 1
        simple_contours += contour_count
        points.extend(glyph_points)
    payload = b"".join(struct.pack("<hh", x, y) for x, y in points)
    values = array("h")
    values.frombytes(payload)
    if values.itemsize != 2:
        raise ValueError("host signed-short width is not 16 bits")
    if sys.byteorder == "big":
        values.byteswap()
    report = {
        "family": expected["family"],
        "source_file": path.name,
        "source_bytes": path.stat().st_size,
        "source_sha256": expected["sha256"],
        "git_blob_sha": blob_sha,
        "google_fonts_commit": COMMIT,
        "units_per_em": units_per_em,
        "font_bounds": list(font_bounds),
        "loca_format": loca_format,
        "glyph_count": glyph_count,
        "simple_glyphs": simple_glyphs,
        "composite_glyphs": composite_glyphs,
        "empty_glyphs": empty_glyphs,
        "simple_contours": simple_contours,
        "simple_points": len(points),
        "coordinate_values": len(values),
        "decoded_bytes": len(payload),
        "minimum": min(values),
        "maximum": max(values),
        "distinct_values": len(set(values)),
        "transitions": sum(left != right for left, right in zip(values, values[1:])),
        "glyph_boundaries_sha256": boundary_digest.hexdigest(),
        "decoded_sha256": hashlib.sha256(payload).hexdigest(),
    }
    for key in (
        "glyph_count", "simple_glyphs", "composite_glyphs", "empty_glyphs",
        "simple_contours", "simple_points", "coordinate_values", "minimum",
        "maximum", "distinct_values", "transitions",
    ):
        if report[key] != expected[key]:
            raise ValueError(f"{path.name}: statistic {key} changed: {report[key]} != {expected[key]}")
    if report["glyph_boundaries_sha256"] != expected["boundaries_sha256"]:
        raise ValueError(f"{path.name}: simple-glyph boundary sequence changed")
    if report["decoded_sha256"] != expected["payload_sha256"]:
        raise ValueError(f"{path.name}: decoded coordinate payload changed")
    return payload, report


def validate_licenses(download_dir: Path) -> None:
    for expected in SOURCES:
        family = str(expected["family"])
        path = download_dir / f"{family}__LICENSE.txt"
        if (
            not path.is_file()
            or path.stat().st_size != LICENSE_BYTES
            or file_hash(path, "sha256") != LICENSE_SHA256
        ):
            raise ValueError(f"missing or changed Apache-2.0 license for {family}")
        text = path.read_text(encoding="utf-8")
        if "Apache License" not in text or "Version 2.0" not in text:
            raise ValueError(f"unexpected license text for {family}")


def decode_all(download_dir: Path) -> list[tuple[Path, bytes, dict[str, object]]]:
    validate_licenses(download_dir)
    decoded = []
    for expected in SOURCES:
        path = download_dir / str(expected["name"])
        if not path.is_file():
            raise SystemExit(f"missing source: {path}")
        payload, report = decode_font(path, expected)
        decoded.append((path, payload, report))
    if aggregate_hash(decoded) != AGGREGATE_SHA256:
        raise ValueError("aggregate decoded coordinate hash changed")
    return decoded


def aggregate_hash(decoded: list[tuple[Path, bytes, dict[str, object]]]) -> str:
    digest = hashlib.sha256()
    for _path, payload, _report in decoded:
        digest.update(payload)
    return digest.hexdigest()


def inspect_command(args: argparse.Namespace) -> None:
    decoded = decode_all(args.download_dir)
    reports = [report for _path, _payload, report in decoded]
    result = {
        "dataset_id": DATASET_ID,
        "sample_count": len(reports),
        "simple_glyphs": sum(int(report["simple_glyphs"]) for report in reports),
        "value_count": sum(int(report["coordinate_values"]) for report in reports),
        "total_size_bytes": sum(int(report["decoded_bytes"]) for report in reports),
        "aggregate_payload_sha256": aggregate_hash(decoded),
        "samples": reports,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    decoded = decode_all(args.download_dir)
    family_dir = args.samples_dir / SERIES_ID
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True)
    rows = []
    for source, payload, report in decoded:
        points = int(report["simple_points"])
        output = family_dir / f"{report['family']}_p{points}_xy_i16le.bin"
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": source.relative_to(args.data_root).as_posix(),
            "source_file": source.name,
            "family": report["family"],
            "value_count": int(report["coordinate_values"]),
            "sample_size_bytes": len(payload),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "sample_geometry": "2d_truetype_outline_points",
            "sample_shape": [points, 2],
            "sample_axes": ["simple_glyph_point", "xy_coordinate"],
            "natural_record_kind": "font_simple_glyph_outline_set",
            "minimum": report["minimum"],
            "maximum": report["maximum"],
            "distinct_values": report["distinct_values"],
            "sha256": report["decoded_sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "google_fonts_commit": COMMIT,
        "sample_count": len(rows),
        "simple_glyphs": sum(int(report["simple_glyphs"]) for _p, _b, report in decoded),
        "value_count": sum(int(row["value_count"]) for row in rows),
        "total_size_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "aggregate_payload_sha256": aggregate_hash(decoded),
        "source_inspections": [report for _p, _b, report in decoded],
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: stats[key] for key in (
        "dataset_id", "sample_count", "simple_glyphs", "value_count",
        "total_size_bytes", "aggregate_payload_sha256",
    )}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    decoded = decode_all(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if len(rows) != len(SOURCES):
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs = set()
    for row, (source, payload, report) in zip(rows, decoded):
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if row.get("source_file") != source.name or not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output mismatch for {source.name}")
        if row.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise SystemExit(f"indexed hash mismatch for {source.name}")
        if row.get("sample_shape") != [int(report["simple_points"]), 2]:
            raise SystemExit(f"indexed shape mismatch for {source.name}")
    actual_outputs = {
        path.resolve()
        for path in args.data_root.joinpath("samples", DATASET_ID).glob("*/*.bin")
    }
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text())
    expected_values = sum(int(report["coordinate_values"]) for _p, _b, report in decoded)
    expected_bytes = sum(len(payload) for _p, payload, _r in decoded)
    if (
        stats.get("sample_count") != len(SOURCES)
        or stats.get("value_count") != expected_values
        or stats.get("total_size_bytes") != expected_bytes
        or stats.get("aggregate_payload_sha256") != aggregate_hash(decoded)
    ):
        raise SystemExit("ingest stats do not match verified totals")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(SOURCES),
        "verified_values": expected_values,
        "verified_bytes": expected_bytes,
        "aggregate_payload_sha256": aggregate_hash(decoded),
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    inspect_parser.add_argument("--report", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect_command(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
