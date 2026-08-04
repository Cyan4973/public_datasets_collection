#!/usr/bin/env python3
"""Strict build and verification for LeCroy WAVEDESC WORD traces."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import tomllib
import zlib


EXPECTED_FILES = 21
EXPECTED_SOURCE_BYTES = 30_007_565
EXPECTED_VALUES = 15_000_034
EXPECTED_SAMPLE_BYTES = 30_000_068
DATASET_ID = "zenodo_lecroy_oscilloscope_i16"
SERIES_ID = "hypervelocity_impact_adc_i16"


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def i16(data: bytes, offset: int, endian: str) -> int:
    return struct.unpack_from(endian + "h", data, offset)[0]


def i32(data: bytes, offset: int, endian: str) -> int:
    return struct.unpack_from(endian + "i", data, offset)[0]


def f32(data: bytes, offset: int, endian: str) -> float:
    return struct.unpack_from(endian + "f", data, offset)[0]


def ascii_field(data: bytes, offset: int, size: int) -> str:
    raw = data[offset : offset + size]
    return raw.split(b"\0", 1)[0].decode("ascii", errors="strict").strip()


def parse_trc(data: bytes, label: str) -> tuple[dict[str, object], bytes]:
    descriptor_offset = data.find(b"WAVEDESC", 0, min(len(data), 131_072))
    if descriptor_offset < 0 or descriptor_offset + 346 > len(data):
        raise ValueError(f"{label}: missing or truncated WAVEDESC")
    candidates: list[tuple[str, int]] = []
    for endian, expected_order in ((">", 0), ("<", 1)):
        comm_type = i16(data, descriptor_offset + 32, endian)
        comm_order = i16(data, descriptor_offset + 34, endian)
        if comm_type in (0, 1) and comm_order == expected_order:
            candidates.append((endian, comm_type))
    if len(candidates) != 1:
        raise ValueError(f"{label}: ambiguous byte order {candidates}")
    endian, comm_type = candidates[0]
    if comm_type != 1:
        raise ValueError(f"{label}: COMM_TYPE is not WORD")
    block_sizes = [i32(data, descriptor_offset + 36 + index * 4, endian) for index in range(10)]
    if any(value < 0 for value in block_sizes):
        raise ValueError(f"{label}: negative descriptor block size")
    descriptor_bytes = block_sizes[0]
    wave_bytes = block_sizes[6]
    if descriptor_bytes < 346 or descriptor_bytes > 1_000_000:
        raise ValueError(f"{label}: implausible descriptor size {descriptor_bytes}")
    wave_count = i32(data, descriptor_offset + 116, endian)
    subarrays = i32(data, descriptor_offset + 144, endian)
    if wave_count <= 0 or subarrays <= 0 or wave_count % subarrays:
        raise ValueError(f"{label}: invalid waveform geometry")
    if wave_bytes != wave_count * 2:
        raise ValueError(f"{label}: waveform byte/count mismatch")
    wave_offset = descriptor_offset + sum(block_sizes[:6])
    declared_end = descriptor_offset + sum(block_sizes)
    if wave_offset < descriptor_offset + descriptor_bytes:
        raise ValueError(f"{label}: waveform overlaps descriptor")
    if wave_offset + wave_bytes > len(data) or declared_end != len(data):
        raise ValueError(
            f"{label}: full-file bounds mismatch wave_end={wave_offset + wave_bytes} "
            f"declared_end={declared_end} file={len(data)}"
        )
    vertical_gain = f32(data, descriptor_offset + 156, endian)
    vertical_offset = f32(data, descriptor_offset + 160, endian)
    horizontal_interval = f32(data, descriptor_offset + 176, endian)
    if not all(math.isfinite(value) for value in (vertical_gain, vertical_offset, horizontal_interval)):
        raise ValueError(f"{label}: non-finite scale metadata")
    if vertical_gain == 0.0 or horizontal_interval <= 0.0:
        raise ValueError(f"{label}: invalid scale metadata")
    payload = data[wave_offset : wave_offset + wave_bytes]
    values = [item[0] for item in struct.iter_unpack(endian + "h", payload)]
    distinct = len(set(values))
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if distinct < 2 or transitions == 0:
        raise ValueError(f"{label}: constant waveform")
    result = {
        "source_path": label,
        "endianness": "big" if endian == ">" else "little",
        "instrument_name": ascii_field(data, descriptor_offset + 76, 16),
        "trace_label": ascii_field(data, descriptor_offset + 96, 16),
        "wave_values": wave_count,
        "wave_bytes": wave_bytes,
        "subarray_count": subarrays,
        "values_per_subarray": wave_count // subarrays,
        "wave_data_offset": wave_offset,
        "minimum": min(values),
        "maximum": max(values),
        "distinct": distinct,
        "transitions": transitions,
        "zero_count": values.count(0),
        "vertical_gain": vertical_gain,
        "vertical_offset": vertical_offset,
        "horizontal_interval": horizontal_interval,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 6),
    }
    return result, payload


def load_sources(download_dir: Path) -> list[Path]:
    inventory_path = download_dir / "source_inventory.json"
    if not inventory_path.is_file():
        raise ValueError(f"missing source inventory: {inventory_path}")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(inventory, list) or len(inventory) != EXPECTED_FILES:
        raise ValueError(f"expected {EXPECTED_FILES} inventory rows")
    if sum(int(row["bytes"]) for row in inventory) != EXPECTED_SOURCE_BYTES:
        raise ValueError("source byte total changed")
    expected: set[str] = set()
    for row in inventory:
        relative_path = str(row["relative_path"])
        source = download_dir / relative_path
        if not source.is_file() or source.stat().st_size != int(row["bytes"]):
            raise ValueError(f"missing or changed source: {relative_path}")
        if md5_file(source) != str(row["md5"]):
            raise ValueError(f"MD5 mismatch: {relative_path}")
        expected.add(relative_path)
    paths = sorted(download_dir.glob("*.trc"))
    actual = {str(path.relative_to(download_dir)) for path in paths}
    if actual != expected:
        raise ValueError(f"source set mismatch missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    return paths


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(data_root: Path) -> None:
    download_dir = data_root / "downloads" / DATASET_ID
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    paths = load_sources(download_dir)
    for target in (sample_dir, index_dir, filtered_dir):
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    payload_hashes: set[str] = set()
    for source in paths:
        parsed, payload = parse_trc(source.read_bytes(), source.name)
        if parsed["endianness"] != "little" or parsed["subarray_count"] != 1:
            raise ValueError(f"unsupported accepted geometry: {source.name}")
        payload_hash = sha256_bytes(payload)
        if payload_hash in payload_hashes:
            raise ValueError(f"duplicate waveform payload: {source.name}")
        payload_hashes.add(payload_hash)
        output = sample_dir / f"{source.stem}.bin"
        output.write_bytes(payload)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(output.relative_to(data_root)),
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": len(payload),
                "value_count": int(parsed["wave_values"]),
                "sample_shape": [int(parsed["wave_values"])],
                "sample_axes": ["sample_time"],
                "source_path": source.name,
                "instrument_name": parsed["instrument_name"],
                "vertical_gain": parsed["vertical_gain"],
                "vertical_offset": parsed["vertical_offset"],
                "horizontal_interval": parsed["horizontal_interval"],
                "minimum": parsed["minimum"],
                "maximum": parsed["maximum"],
                "distinct": parsed["distinct"],
                "transitions": parsed["transitions"],
                "sha256": payload_hash,
            }
        )
    total_values = sum(int(row["value_count"]) for row in rows)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    if len(rows) != EXPECTED_FILES or total_values != EXPECTED_VALUES or total_bytes != EXPECTED_SAMPLE_BYTES:
        raise ValueError(
            f"aggregate output changed samples={len(rows)} values={total_values} bytes={total_bytes}"
        )
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "source_files": len(paths),
        "primary_samples": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "distinct_sample_lengths": len({int(row["value_count"]) for row in rows}),
        "minimum_sample_values": min(int(row["value_count"]) for row in rows),
        "maximum_sample_values": max(int(row["value_count"]) for row in rows),
        "minimum_distinct_values": min(int(row["distinct"]) for row in rows),
        "maximum_distinct_values": max(int(row["distinct"]) for row in rows),
    }
    (filtered_dir / "ingest_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(stats, indent=2, sort_keys=True))


def verify(data_root: Path, manifest_path: Path) -> None:
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        raise ValueError("manifest dataset identity mismatch")
    series = manifest.get("series", [])
    if not isinstance(series, list) or len(series) != 1:
        raise ValueError("manifest must declare exactly one series")
    declared = series[0]
    if (
        declared.get("id") != SERIES_ID
        or declared.get("numeric_kind") != "int"
        or declared.get("bit_width") != 16
        or declared.get("endianness") != "little"
        or declared.get("sample_count") != EXPECTED_FILES
        or declared.get("total_size_bytes") != EXPECTED_SAMPLE_BYTES
    ):
        raise ValueError("manifest series declaration changed")
    download_dir = data_root / "downloads" / DATASET_ID
    paths = load_sources(download_dir)
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    if not index_path.is_file():
        raise ValueError("missing sample index")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    indexed = {str(row["source_path"]): row for row in rows}
    if len(rows) != EXPECTED_FILES or len(indexed) != EXPECTED_FILES:
        raise ValueError("sample index count or keys changed")
    expected_outputs: set[str] = set()
    verified_values = 0
    verified_bytes = 0
    for source in paths:
        parsed, payload = parse_trc(source.read_bytes(), source.name)
        if source.name not in indexed:
            raise ValueError(f"missing indexed source: {source.name}")
        row = indexed[source.name]
        sample_path = str(row["sample_path"])
        sample = data_root / sample_path
        if not sample.is_file() or sample.read_bytes() != payload:
            raise ValueError(f"sample differs from source waveform bytes: {sample_path}")
        if (
            row.get("dataset_id") != DATASET_ID
            or row.get("series_id") != SERIES_ID
            or row.get("numeric_kind") != "int"
            or row.get("bit_width") != 16
            or row.get("endianness") != "little"
            or row.get("element_size_bytes") != 2
            or row.get("value_count") != parsed["wave_values"]
            or row.get("sample_size_bytes") != len(payload)
            or row.get("sha256") != sha256_bytes(payload)
        ):
            raise ValueError(f"index metadata mismatch: {sample_path}")
        expected_outputs.add(sample_path)
        verified_values += int(row["value_count"])
        verified_bytes += len(payload)
    sample_root = data_root / "samples" / DATASET_ID / SERIES_ID
    actual_outputs = {
        str(path.relative_to(data_root)) for path in sample_root.glob("*.bin") if path.is_file()
    }
    if actual_outputs != expected_outputs:
        raise ValueError("sample directory contains missing or unindexed files")
    if verified_values != EXPECTED_VALUES or verified_bytes != EXPECTED_SAMPLE_BYTES:
        raise ValueError("verified aggregate values or bytes changed")
    print(
        f"verify_ok files={len(paths)} samples={len(expected_outputs)} "
        f"values={verified_values} bytes={verified_bytes}"
    )


def inspect(download_dir: Path, output_dir: Path) -> None:
    paths = load_sources(download_dir)
    rows: list[dict[str, object]] = []
    hashes: dict[str, str] = {}
    for path in paths:
        row, _ = parse_trc(path.read_bytes(), path.name)
        payload_hash = str(row["payload_sha256"])
        if payload_hash in hashes:
            raise ValueError(f"duplicate waveform payload: {path.name} and {hashes[payload_hash]}")
        hashes[payload_hash] = path.name
        rows.append(row)
        print(
            f"ok source={path.name} instrument={row['instrument_name']!r} "
            f"trace={row['trace_label']!r} values={row['wave_values']} "
            f"range={row['minimum']}..{row['maximum']} distinct={row['distinct']} "
            f"zlib_ratio={row['zlib_ratio']}"
        )
    total_values = sum(int(row["wave_values"]) for row in rows)
    if total_values != EXPECTED_VALUES:
        raise ValueError(f"waveform value total changed: {total_values}")
    output_dir.mkdir(parents=True, exist_ok=True)
    columns = tuple(rows[0].keys())
    with (output_dir / "full_preflight.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    ratios = [float(row["zlib_ratio"]) for row in rows]
    summary = {
        "files": len(rows),
        "natural_samples": sum(int(row["subarray_count"]) for row in rows),
        "total_values": total_values,
        "total_waveform_bytes": total_values * 2,
        "distinct_sample_lengths": len({int(row["values_per_subarray"]) for row in rows}),
        "minimum_sample_values": min(int(row["values_per_subarray"]) for row in rows),
        "maximum_sample_values": max(int(row["values_per_subarray"]) for row in rows),
        "minimum_distinct_values": min(int(row["distinct"]) for row in rows),
        "maximum_distinct_values": max(int(row["distinct"]) for row in rows),
        "minimum_zlib_ratio": min(ratios),
        "median_zlib_ratio": statistics.median(ratios),
        "maximum_zlib_ratio": max(ratios),
        "unique_payloads": len(hashes),
    }
    (output_dir / "full_preflight_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    inspect_parser.add_argument("--output-dir", type=Path, required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--data-root", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--data-root", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args.download_dir, args.output_dir)
    elif args.command == "build":
        build(args.data_root)
    elif args.command == "verify":
        verify(args.data_root, args.manifest)


if __name__ == "__main__":
    main()
