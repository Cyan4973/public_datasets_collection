#!/usr/bin/env python3
"""Extract and independently verify native LAS point-format-6 GPS time."""

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


DATASET_ID = "dc_lidar_2015_gps_time_f64"
EXPECTED_NAMES = ("1812.las", "2016.las", "2315.las")
EXPECTED_URLS = {
    name: f"https://dc-lidar-2015.s3.amazonaws.com/Classified_LAS/{name}"
    for name in EXPECTED_NAMES
}
GPS_TIME_OFFSET = 22
EXPECTED_POINT_FORMAT = 6
EXPECTED_RECORD_LENGTH = 30
MIN_SAMPLE_VALUES = 1_000
MIN_TOTAL_VALUES = 10_000
MAX_PRIMARY_BYTES = 1_000_000_000
BLOCK_POINTS = 131_072


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
    version_major = header[24]
    version_minor = header[25]
    header_size = struct.unpack_from("<H", header, 94)[0]
    point_offset = struct.unpack_from("<I", header, 96)[0]
    raw_format = header[104]
    record_length = struct.unpack_from("<H", header, 105)[0]
    legacy_count = struct.unpack_from("<I", header, 107)[0]
    extended_count = struct.unpack_from("<Q", header, 247)[0]
    if raw_format & 0xC0:
        raise ValueError(f"{path.name}: compressed LAS point records are unsupported")
    point_format = raw_format & 0x3F
    if (version_major, version_minor) < (1, 4):
        raise ValueError(f"{path.name}: expected LAS 1.4, found {version_major}.{version_minor}")
    if point_format != EXPECTED_POINT_FORMAT:
        raise ValueError(
            f"{path.name}: expected point format 6, found {point_format}"
        )
    if record_length != EXPECTED_RECORD_LENGTH:
        raise ValueError(
            f"{path.name}: expected 30-byte point records, found {record_length}"
        )
    point_count = extended_count or legacy_count
    if point_count <= 0:
        raise ValueError(f"{path.name}: no point records")
    if header_size < 375 or point_offset < header_size:
        raise ValueError(f"{path.name}: invalid LAS header/point-data offsets")
    point_end = point_offset + point_count * record_length
    if point_end > source_bytes:
        raise ValueError(
            f"{path.name}: point records end at {point_end}, beyond {source_bytes} bytes"
        )
    return LasLayout(
        point_offset=point_offset,
        point_format=point_format,
        record_length=record_length,
        point_count=point_count,
        source_bytes=source_bytes,
    )


def iter_gps_payloads(path: Path, layout: LasLayout) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(layout.point_offset)
        remaining = layout.point_count
        while remaining:
            count = min(remaining, BLOCK_POINTS)
            source = handle.read(count * layout.record_length)
            expected = count * layout.record_length
            if len(source) != expected:
                raise ValueError(
                    f"{path.name}: truncated point block ({len(source)} != {expected})"
                )
            payload = bytearray(count * 8)
            for index in range(count):
                source_start = index * layout.record_length + GPS_TIME_OFFSET
                output_start = index * 8
                payload[output_start : output_start + 8] = source[
                    source_start : source_start + 8
                ]
            yield bytes(payload)
            remaining -= count


def scan_payloads(payloads: Iterator[bytes]) -> dict[str, float | int | bool]:
    count = 0
    minimum = math.inf
    maximum = -math.inf
    first = None
    previous = None
    nonconstant = False
    nondecreasing = 0
    zero_deltas = 0
    delta_count = 0
    for payload in payloads:
        for (value,) in struct.iter_unpack("<d", payload):
            if not math.isfinite(value):
                raise ValueError(f"non-finite GPS time at value {count}")
            if first is None:
                first = value
            elif value != first:
                nonconstant = True
            if previous is not None:
                delta = value - previous
                nondecreasing += delta >= 0
                zero_deltas += delta == 0
                delta_count += 1
            previous = value
            minimum = min(minimum, value)
            maximum = max(maximum, value)
            count += 1
    if count == 0:
        raise ValueError("empty GPS-time stream")
    if not nonconstant:
        raise ValueError("constant GPS-time stream")
    return {
        "value_count": count,
        "min": minimum,
        "max": maximum,
        "nonconstant": nonconstant,
        "nondecreasing_fraction": nondecreasing / delta_count,
        "zero_delta_fraction": zero_deltas / delta_count,
    }


def inspect(paths: list[Path]) -> None:
    if tuple(path.name for path in paths) != EXPECTED_NAMES:
        raise ValueError(f"expected sources in order: {EXPECTED_NAMES}")
    total = 0
    for path in paths:
        layout = read_layout(path)
        total += layout.point_count
        print(
            f"source={path.name} format={layout.point_format} "
            f"record_length={layout.record_length} points={layout.point_count}"
        )
    print(f"semantic_validation=ok files={len(paths)} points={total}")


def build(
    download_dir: Path,
    samples_dir: Path,
    index_path: Path,
    stats_path: Path,
) -> None:
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    output_dir = samples_dir / "dc_lidar_gps_time_f64"
    output_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    records = []
    for name in EXPECTED_NAMES:
        source = download_dir / name
        layout = read_layout(source)
        output = output_dir / f"{source.stem}_gps_time_f64_n{layout.point_count:010d}.bin"
        with output.open("wb") as handle:
            for payload in iter_gps_payloads(source, layout):
                handle.write(payload)
        metrics = scan_payloads(iter_gps_payloads(source, layout))
        expected_bytes = layout.point_count * 8
        if output.stat().st_size != expected_bytes:
            raise ValueError(f"{name}: output size mismatch")
        row = {
            "dataset_id": DATASET_ID,
            "series_id": "dc_lidar_gps_time_f64",
            "role": "primary",
            "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": expected_bytes,
            "value_count": layout.point_count,
            "sample_format": "raw homogeneous float64 LAS GPS-time array",
            "sample_geometry": "las_point_attribute_stream",
            "sample_rank": 1,
            "sample_shape": [layout.point_count],
            "sample_axes": ["point"],
            "natural_record_kind": "las_tile",
            "source_field": "GPS Time",
            "source_sample": name,
            "source_url": EXPECTED_URLS[name],
            "source_bytes": layout.source_bytes,
            "point_format": layout.point_format,
            "point_record_length": layout.record_length,
            "gps_time_offset": GPS_TIME_OFFSET,
            "min": metrics["min"],
            "max": metrics["max"],
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
        if row.get("numeric_kind") != "float" or row.get("bit_width") != 64:
            raise ValueError("indexed sample is not float64")
        source = download_dir / row["source_sample"]
        layout = read_layout(source)
        sample = data_root / row["sample_path"]
        expected_bytes = layout.point_count * 8
        if sample.stat().st_size != expected_bytes:
            raise ValueError(f"{sample}: wrong output size")
        with sample.open("rb") as output:
            for expected in iter_gps_payloads(source, layout):
                actual = output.read(len(expected))
                if actual != expected:
                    raise ValueError(f"{sample}: source byte mismatch")
                if any(
                    not math.isfinite(value)
                    for (value,) in struct.iter_unpack("<d", actual)
                ):
                    raise ValueError(f"{sample}: non-finite value")
            if output.read(1):
                raise ValueError(f"{sample}: trailing output bytes")
        if int(row["value_count"]) != layout.point_count:
            raise ValueError(f"{sample}: wrong indexed value count")
        counts.append(layout.point_count)
        total_bytes += expected_bytes

    median_values = statistics.median(counts)
    if sum(counts) < MIN_TOTAL_VALUES or median_values < MIN_SAMPLE_VALUES:
        raise ValueError("acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError("primary output cap failed")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"total_values={sum(counts)} total_bytes={total_bytes} "
        f"median={median_values:g}"
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
