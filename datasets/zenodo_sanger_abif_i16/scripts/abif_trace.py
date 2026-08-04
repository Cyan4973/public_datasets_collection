#!/usr/bin/env python3
"""Strict dependency-free build and verification of 16-bit ABIF traces."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import tomllib
import zlib


ENTRY = struct.Struct(">4sIHHIIII")
TRACE_NUMBERS = (9, 10, 11, 12)
TYPE_NAMES = {3: "word_u16", 4: "short_i16"}
EXPECTED_FILES = 63
EXPECTED_SOURCE_BYTES = 18_119_348
EXPECTED_SAMPLES = 252
EXPECTED_VALUES = 3_050_572
EXPECTED_SAMPLE_BYTES = 6_101_144
MIN_TRACE_VALUES = 1_000
MIN_TOTAL_VALUES = 500_000
DATASET_ID = "zenodo_sanger_abif_i16"
SERIES_ID = "sanger_processed_dye_trace_i16"


def parse_entry(data: bytes, offset: int, label: str) -> dict[str, object]:
    if offset < 0 or offset + ENTRY.size > len(data):
        raise ValueError(f"{label}: directory entry is out of bounds")
    tag, number, element_type, element_size, count, size, data_offset, handle = ENTRY.unpack_from(
        data, offset
    )
    return {
        "tag": tag,
        "number": number,
        "element_type": element_type,
        "element_size": element_size,
        "count": count,
        "size": size,
        "data_offset": data_offset,
        "handle": handle,
        "entry_offset": offset,
    }


def entry_payload(data: bytes, entry: dict[str, object], label: str) -> bytes:
    size = int(entry["size"])
    if size <= 4:
        packed = struct.pack(">I", int(entry["data_offset"]))
        return packed[:size]
    offset = int(entry["data_offset"])
    if offset < 0 or offset + size > len(data):
        raise ValueError(f"{label}: payload is out of bounds")
    return data[offset : offset + size]


def inspect_file(path: Path, download_dir: Path) -> list[dict[str, object]]:
    data = path.read_bytes()
    label = str(path.relative_to(download_dir))
    if len(data) < 34 or data[:4] != b"ABIF":
        raise ValueError(f"{label}: missing ABIF header")
    version = struct.unpack_from(">H", data, 4)[0]
    if version < 100 or version > 999:
        raise ValueError(f"{label}: implausible ABIF version {version}")
    root = parse_entry(data, 6, f"{label}:root")
    if root["tag"] != b"tdir" or int(root["element_size"]) != ENTRY.size:
        raise ValueError(f"{label}: invalid root directory entry")
    directory_count = int(root["count"])
    directory_size = int(root["size"])
    directory_offset = int(root["data_offset"])
    used_directory_size = directory_count * ENTRY.size
    if (
        directory_count <= 0
        or directory_size < used_directory_size
        or directory_size % ENTRY.size != 0
    ):
        raise ValueError(f"{label}: inconsistent directory dimensions")
    if directory_offset < 0 or directory_offset + directory_size > len(data):
        raise ValueError(f"{label}: directory table is out of bounds")
    padding = data[
        directory_offset + used_directory_size : directory_offset + directory_size
    ]
    if any(padding):
        raise ValueError(f"{label}: nonzero bytes after used directory entries")
    entries: dict[tuple[bytes, int], dict[str, object]] = {}
    for index in range(directory_count):
        entry = parse_entry(data, directory_offset + index * ENTRY.size, f"{label}:entry[{index}]")
        key = (bytes(entry["tag"]), int(entry["number"]))
        if key in entries:
            raise ValueError(f"{label}: duplicate directory tag {key!r}")
        entries[key] = entry

    trace_entries = []
    for number in TRACE_NUMBERS:
        key = (b"DATA", number)
        if key not in entries:
            raise ValueError(f"{label}: missing processed trace DATA{number}")
        entry = entries[key]
        element_type = int(entry["element_type"])
        element_size = int(entry["element_size"])
        count = int(entry["count"])
        size = int(entry["size"])
        if element_type not in TYPE_NAMES or element_size != 2 or size != count * 2:
            raise ValueError(
                f"{label}: DATA{number} is not an exact two-byte integer array "
                f"type={element_type} element_size={element_size} count={count} size={size}"
            )
        if count < MIN_TRACE_VALUES:
            raise ValueError(f"{label}: DATA{number} is too short: {count}")
        trace_entries.append(entry)
    lengths = {int(entry["count"]) for entry in trace_entries}
    if len(lengths) != 1:
        raise ValueError(f"{label}: processed trace channel lengths differ: {sorted(lengths)}")

    rows: list[dict[str, object]] = []
    for number, entry in zip(TRACE_NUMBERS, trace_entries):
        payload = entry_payload(data, entry, f"{label}:DATA{number}")
        element_type = int(entry["element_type"])
        fmt = ">H" if element_type == 3 else ">h"
        values = [item[0] for item in struct.iter_unpack(fmt, payload)]
        distinct = len(set(values))
        transitions = sum(left != right for left, right in zip(values, values[1:]))
        if distinct < 2 or transitions == 0:
            raise ValueError(f"{label}: DATA{number} is constant")
        rows.append(
            {
                "source_path": label,
                "abif_version": version,
                "directory_entries": directory_count,
                "trace_tag": f"DATA{number}",
                "element_type": TYPE_NAMES[element_type],
                "values": len(values),
                "bytes": len(payload),
                "minimum": min(values),
                "maximum": max(values),
                "distinct": distinct,
                "transitions": transitions,
                "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 6),
                "data_offset": int(entry["data_offset"]),
            }
        )
    return rows


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_inventory(download_dir: Path) -> tuple[list[dict[str, object]], list[Path]]:
    inventory_path = download_dir / "source_inventory.json"
    if not inventory_path.is_file():
        raise ValueError(f"missing downloader inventory: {inventory_path}")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(inventory, list) or len(inventory) != EXPECTED_FILES:
        raise ValueError(f"expected {EXPECTED_FILES} inventoried files")
    if sum(int(row["bytes"]) for row in inventory) != EXPECTED_SOURCE_BYTES:
        raise ValueError("source inventory byte total changed")
    expected_paths: set[str] = set()
    for row in inventory:
        if not isinstance(row, dict):
            raise ValueError("malformed source inventory row")
        relative_path = str(row["relative_path"])
        source = download_dir / relative_path
        if not source.is_file() or source.stat().st_size != int(row["bytes"]):
            raise ValueError(f"missing or changed source: {relative_path}")
        if md5_file(source) != str(row["md5"]):
            raise ValueError(f"MD5 mismatch: {relative_path}")
        expected_paths.add(relative_path)
    paths = sorted(
        path
        for path in download_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".ab1", ".abi"}
    )
    actual_paths = {str(path.relative_to(download_dir)) for path in paths}
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        raise ValueError(f"payload inventory mismatch missing={missing} extra={extra}")
    return inventory, paths


def source_trace_to_le(source_data: bytes, row: dict[str, object]) -> bytes:
    if row["element_type"] != "short_i16":
        raise ValueError(f"unsupported accepted trace type: {row['element_type']}")
    offset = int(row["data_offset"])
    size = int(row["bytes"])
    payload = source_data[offset : offset + size]
    if len(payload) != size:
        raise ValueError("trace payload became truncated")
    values = [item[0] for item in struct.iter_unpack(">h", payload)]
    return struct.pack(f"<{len(values)}h", *values)


def sample_name(source_path: str, trace_tag: str, values: int) -> str:
    source = Path(source_path)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source.stem).strip("._")
    return f"{source.parent.name}__{stem}__{trace_tag.lower()}__n{values:05d}.bin"


def build(data_root: Path) -> None:
    download_dir = data_root / "downloads" / DATASET_ID
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    _, paths = load_inventory(download_dir)
    for target in (sample_dir, index_dir, filtered_dir):
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    index_rows: list[dict[str, object]] = []
    for path in paths:
        source_data = path.read_bytes()
        source_path = str(path.relative_to(download_dir))
        for row in inspect_file(path, download_dir):
            payload = source_trace_to_le(source_data, row)
            filename = sample_name(source_path, str(row["trace_tag"]), int(row["values"]))
            output = sample_dir / filename
            if output.exists():
                raise ValueError(f"sample name collision: {filename}")
            output.write_bytes(payload)
            sample_path = str(output.relative_to(data_root))
            index_rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": SERIES_ID,
                    "sample_path": sample_path,
                    "numeric_kind": "int",
                    "bit_width": 16,
                    "endianness": "little",
                    "element_size_bytes": 2,
                    "sample_size_bytes": len(payload),
                    "value_count": int(row["values"]),
                    "sample_shape": [int(row["values"])],
                    "sample_axes": ["electrophoretic_scan_time"],
                    "source_path": source_path,
                    "source_trace_tag": row["trace_tag"],
                    "source_element_type": row["element_type"],
                    "minimum": row["minimum"],
                    "maximum": row["maximum"],
                    "distinct": row["distinct"],
                    "transitions": row["transitions"],
                    "sha256": sha256_bytes(payload),
                }
            )
    total_values = sum(int(row["value_count"]) for row in index_rows)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in index_rows)
    if (
        len(index_rows) != EXPECTED_SAMPLES
        or total_values != EXPECTED_VALUES
        or total_bytes != EXPECTED_SAMPLE_BYTES
    ):
        raise ValueError(
            f"aggregate output changed samples={len(index_rows)} values={total_values} "
            f"bytes={total_bytes}"
        )
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in index_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "source_files": len(paths),
        "primary_samples": len(index_rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "minimum_sample_values": min(int(row["value_count"]) for row in index_rows),
        "maximum_sample_values": max(int(row["value_count"]) for row in index_rows),
        "distinct_sample_lengths": len({int(row["value_count"]) for row in index_rows}),
        "minimum_distinct_values": min(int(row["distinct"]) for row in index_rows),
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
        or declared.get("sample_count") != EXPECTED_SAMPLES
        or declared.get("total_size_bytes") != EXPECTED_SAMPLE_BYTES
    ):
        raise ValueError("manifest series declaration changed")

    download_dir = data_root / "downloads" / DATASET_ID
    _, paths = load_inventory(download_dir)
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    if not index_path.is_file():
        raise ValueError("missing sample index")
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    indexed = {
        (str(row["source_path"]), str(row["source_trace_tag"])): row
        for row in index_rows
    }
    if len(index_rows) != EXPECTED_SAMPLES or len(indexed) != EXPECTED_SAMPLES:
        raise ValueError("sample index count or keys changed")

    expected_sample_paths: set[str] = set()
    verified_values = 0
    verified_bytes = 0
    for path in paths:
        source_data = path.read_bytes()
        source_path = str(path.relative_to(download_dir))
        for trace_row in inspect_file(path, download_dir):
            key = (source_path, str(trace_row["trace_tag"]))
            if key not in indexed:
                raise ValueError(f"missing indexed trace: {key}")
            row = indexed[key]
            expected = source_trace_to_le(source_data, trace_row)
            sample_path = str(row["sample_path"])
            sample = data_root / sample_path
            if not sample.is_file() or sample.read_bytes() != expected:
                raise ValueError(f"sample bytes differ from decoded source: {sample_path}")
            if (
                row.get("dataset_id") != DATASET_ID
                or row.get("series_id") != SERIES_ID
                or row.get("numeric_kind") != "int"
                or row.get("bit_width") != 16
                or row.get("endianness") != "little"
                or row.get("element_size_bytes") != 2
                or row.get("value_count") != trace_row["values"]
                or row.get("sample_size_bytes") != len(expected)
                or row.get("sha256") != sha256_bytes(expected)
            ):
                raise ValueError(f"sample index metadata mismatch: {sample_path}")
            expected_sample_paths.add(sample_path)
            verified_values += int(row["value_count"])
            verified_bytes += len(expected)
    sample_root = data_root / "samples" / DATASET_ID / SERIES_ID
    actual_sample_paths = {
        str(path.relative_to(data_root)) for path in sample_root.glob("*.bin") if path.is_file()
    }
    if actual_sample_paths != expected_sample_paths:
        raise ValueError("sample directory contains missing or unindexed outputs")
    if verified_values != EXPECTED_VALUES or verified_bytes != EXPECTED_SAMPLE_BYTES:
        raise ValueError("verified aggregate values or bytes changed")
    print(
        f"verify_ok files={len(paths)} samples={len(expected_sample_paths)} "
        f"values={verified_values} bytes={verified_bytes}"
    )


def inspect(download_dir: Path, output_dir: Path) -> None:
    try:
        _, paths = load_inventory(download_dir)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    rows: list[dict[str, object]] = []
    for path in paths:
        file_rows = inspect_file(path, download_dir)
        rows.extend(file_rows)
        print(
            f"ok source={path.relative_to(download_dir)} traces={len(file_rows)} "
            f"values={file_rows[0]['values']} types="
            f"{','.join(str(row['element_type']) for row in file_rows)}"
        )
    total_values = sum(int(row["values"]) for row in rows)
    total_bytes = sum(int(row["bytes"]) for row in rows)
    if len(rows) != EXPECTED_FILES * 4 or total_values < MIN_TOTAL_VALUES:
        raise SystemExit(
            f"insufficient traces: samples={len(rows)} values={total_values}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    columns = (
        "source_path",
        "abif_version",
        "directory_entries",
        "trace_tag",
        "element_type",
        "values",
        "bytes",
        "minimum",
        "maximum",
        "distinct",
        "transitions",
        "zlib_ratio",
        "data_offset",
    )
    with (output_dir / "abif_preflight.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "files": len(paths),
        "samples": len(rows),
        "total_values": total_values,
        "total_bytes": total_bytes,
        "minimum_sample_values": min(int(row["values"]) for row in rows),
        "maximum_sample_values": max(int(row["values"]) for row in rows),
        "distinct_sample_lengths": len({int(row["values"]) for row in rows}),
        "element_types": sorted({str(row["element_type"]) for row in rows}),
        "minimum_distinct_values": min(int(row["distinct"]) for row in rows),
        "maximum_zlib_ratio": max(float(row["zlib_ratio"]) for row in rows),
    }
    (output_dir / "abif_preflight_summary.json").write_text(
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
