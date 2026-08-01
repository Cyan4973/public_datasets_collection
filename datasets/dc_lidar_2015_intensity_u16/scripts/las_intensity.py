#!/usr/bin/env python3
"""Extract and independently byte-verify LAS point-format-6 intensity values."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
from typing import Iterator


DATASET_ID = "dc_lidar_2015_intensity_u16"
SERIES_ID = "dc_lidar_intensity_u16"
EXPECTED_NAMES = ("1812.las", "2016.las", "2315.las")
EXPECTED_URLS = {
    name: f"https://dc-lidar-2015.s3.amazonaws.com/Classified_LAS/{name}"
    for name in EXPECTED_NAMES
}
INTENSITY_OFFSET = 12
EXPECTED_POINT_FORMAT = 6
EXPECTED_RECORD_LENGTH = 30
MIN_SAMPLE_VALUES = 1_000
MIN_TOTAL_VALUES = 10_000
MAX_PRIMARY_BYTES = 1_000_000_000
BLOCK_POINTS = 262_144


@dataclass(frozen=True)
class LasLayout:
    point_offset: int
    point_format: int
    record_length: int
    point_count: int
    source_bytes: int


def read_layout(path: Path) -> LasLayout:
    if not path.is_file():
        raise ValueError(f"missing LAS source: {path}")
    source_bytes = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(375)
    if len(header) < 255 or header[:4] != b"LASF":
        raise ValueError(f"{path.name}: invalid LAS header")
    version = (header[24], header[25])
    header_size = struct.unpack_from("<H", header, 94)[0]
    point_offset = struct.unpack_from("<I", header, 96)[0]
    raw_format = header[104]
    record_length = struct.unpack_from("<H", header, 105)[0]
    legacy_count = struct.unpack_from("<I", header, 107)[0]
    extended_count = struct.unpack_from("<Q", header, 247)[0]
    if raw_format & 0xC0:
        raise ValueError(f"{path.name}: compressed LAS records are unsupported")
    point_format = raw_format & 0x3F
    if version < (1, 4):
        raise ValueError(f"{path.name}: expected LAS 1.4, found {version[0]}.{version[1]}")
    if point_format != EXPECTED_POINT_FORMAT:
        raise ValueError(f"{path.name}: expected point format 6, found {point_format}")
    if record_length != EXPECTED_RECORD_LENGTH:
        raise ValueError(f"{path.name}: expected 30-byte records, found {record_length}")
    point_count = extended_count or legacy_count
    if point_count <= 0:
        raise ValueError(f"{path.name}: no point records")
    if header_size < 375 or point_offset < header_size:
        raise ValueError(f"{path.name}: invalid header/point-data offsets")
    point_end = point_offset + point_count * record_length
    if point_end > source_bytes:
        raise ValueError(f"{path.name}: point records extend beyond source file")
    return LasLayout(point_offset, point_format, record_length, point_count, source_bytes)


def iter_intensity_payloads(path: Path, layout: LasLayout) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(layout.point_offset)
        remaining = layout.point_count
        while remaining:
            count = min(remaining, BLOCK_POINTS)
            expected = count * layout.record_length
            source = handle.read(expected)
            if len(source) != expected:
                raise ValueError(f"{path.name}: truncated point block")
            payload = bytearray(count * 2)
            payload[0::2] = source[INTENSITY_OFFSET:expected:layout.record_length]
            payload[1::2] = source[INTENSITY_OFFSET + 1:expected:layout.record_length]
            yield bytes(payload)
            remaining -= count


def scan_payloads(payloads: Iterator[bytes]) -> dict[str, float | int | bool]:
    histogram = [0] * 65_536
    count = 0
    first = None
    previous = None
    nonconstant = False
    adjacent_equal = 0
    small_delta = 0
    for payload in payloads:
        for (value,) in struct.iter_unpack("<H", payload):
            histogram[value] += 1
            if first is None:
                first = value
            elif value != first:
                nonconstant = True
            if previous is not None:
                delta = value - previous
                adjacent_equal += delta == 0
                small_delta += abs(delta) <= 16
            previous = value
            count += 1
    if count == 0:
        raise ValueError("empty intensity stream")
    if not nonconstant:
        raise ValueError("constant intensity stream")
    populated = [value for value, frequency in enumerate(histogram) if frequency]
    entropy = -sum(
        (frequency / count) * math.log2(frequency / count)
        for frequency in histogram
        if frequency
    )
    deltas = count - 1
    return {
        "value_count": count,
        "min": populated[0],
        "max": populated[-1],
        "distinct_values": len(populated),
        "nonconstant": nonconstant,
        "adjacent_equal_fraction": adjacent_equal / deltas,
        "absolute_delta_le_16_fraction": small_delta / deltas,
        "entropy_bits_per_value": entropy,
        "upper_byte_zero_fraction": sum(histogram[:256]) / count,
    }


def inspect(paths: list[Path]) -> None:
    if tuple(path.name for path in paths) != EXPECTED_NAMES:
        raise ValueError(f"expected sources in order: {EXPECTED_NAMES}")
    total = 0
    for path in paths:
        layout = read_layout(path)
        metrics = scan_payloads(iter_intensity_payloads(path, layout))
        total += layout.point_count
        print(
            f"source={path.name} format={layout.point_format} "
            f"record_length={layout.record_length} points={layout.point_count} "
            f"min={metrics['min']} max={metrics['max']} "
            f"distinct={metrics['distinct_values']}"
        )
    print(f"semantic_validation=ok files={len(paths)} points={total}")


def build(download_dir: Path, samples_dir: Path, index_path: Path, stats_path: Path) -> None:
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    output_dir = samples_dir / SERIES_ID
    output_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    records = []
    for name in EXPECTED_NAMES:
        source = download_dir / name
        layout = read_layout(source)
        output = output_dir / f"{source.stem}_intensity_u16_n{layout.point_count:010d}.bin"
        with output.open("wb") as handle:
            for payload in iter_intensity_payloads(source, layout):
                handle.write(payload)
        metrics = scan_payloads(iter_intensity_payloads(source, layout))
        expected_bytes = layout.point_count * 2
        if output.stat().st_size != expected_bytes:
            raise ValueError(f"{name}: output size mismatch")
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": expected_bytes,
            "value_count": layout.point_count,
            "sample_format": "raw homogeneous uint16 LAS intensity array",
            "sample_geometry": "las_point_attribute_stream",
            "sample_rank": 1,
            "sample_shape": [layout.point_count],
            "sample_axes": ["point"],
            "natural_record_kind": "las_tile",
            "source_field": "Intensity",
            "source_sample": name,
            "source_url": EXPECTED_URLS[name],
            "source_bytes": layout.source_bytes,
            "point_format": layout.point_format,
            "point_record_length": layout.record_length,
            "intensity_offset": INTENSITY_OFFSET,
            "min": metrics["min"],
            "max": metrics["max"],
            "distinct_values": metrics["distinct_values"],
        }
        rows.append(row)
        records.append({"source_name": name, **metrics})

    counts = [int(row["value_count"]) for row in rows]
    total_values = sum(counts)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    median_values = statistics.median(counts)
    if total_values < MIN_TOTAL_VALUES:
        raise ValueError(f"total values below floor: {total_values}")
    if median_values < MIN_SAMPLE_VALUES:
        raise ValueError(f"median sample below floor: {median_values}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")

    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "sample_count": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_value_count": median_values,
        "records": records,
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(
        f"built samples={len(rows)} primary_values={total_values} "
        f"primary_bytes={total_bytes} median={median_values:g}"
    )


def verify(download_dir: Path, index_path: Path, data_root: Path) -> None:
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if [row.get("source_sample") for row in rows] != list(EXPECTED_NAMES):
        raise ValueError("index source set/order does not match pinned tiles")
    counts = []
    total_bytes = 0
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row.get("role") != "primary":
            raise ValueError("invalid index identity or role")
        if row.get("numeric_kind") != "uint" or row.get("bit_width") != 16:
            raise ValueError("indexed sample is not uint16")
        source = download_dir / row["source_sample"]
        layout = read_layout(source)
        sample = data_root / row["sample_path"]
        expected_bytes = layout.point_count * 2
        if sample.stat().st_size != expected_bytes:
            raise ValueError(f"{sample}: wrong output size")
        with sample.open("rb") as output:
            for expected in iter_intensity_payloads(source, layout):
                actual = output.read(len(expected))
                if actual != expected:
                    raise ValueError(f"{sample}: source byte mismatch")
            if output.read(1):
                raise ValueError(f"{sample}: trailing output bytes")
        metrics = scan_payloads(iter_intensity_payloads(source, layout))
        if int(row["value_count"]) != layout.point_count:
            raise ValueError(f"{sample}: wrong indexed value count")
        if int(row["min"]) != metrics["min"] or int(row["max"]) != metrics["max"]:
            raise ValueError(f"{sample}: indexed range mismatch")
        if int(row["distinct_values"]) != metrics["distinct_values"]:
            raise ValueError(f"{sample}: indexed distinct-value count mismatch")
        counts.append(layout.point_count)
        total_bytes += expected_bytes

    median_values = statistics.median(counts)
    if sum(counts) < MIN_TOTAL_VALUES or median_values < MIN_SAMPLE_VALUES:
        raise ValueError("acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError("primary output cap failed")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"total_values={sum(counts)} total_bytes={total_bytes} median={median_values:g}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("sources", nargs="+", type=Path)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--download-dir", required=True, type=Path)
    build_parser.add_argument("--samples-dir", required=True, type=Path)
    build_parser.add_argument("--index", required=True, type=Path)
    build_parser.add_argument("--stats", required=True, type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--download-dir", required=True, type=Path)
    verify_parser.add_argument("--index", required=True, type=Path)
    verify_parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args.sources)
    elif args.command == "build":
        build(args.download_dir, args.samples_dir, args.index, args.stats)
    else:
        verify(args.download_dir, args.index, args.data_root)


if __name__ == "__main__":
    main()
