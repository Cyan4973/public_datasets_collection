#!/usr/bin/env python3
"""Build and verify the native uint16 silicon EBSD detector plane."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from packbits_tiff import (
    EXPECTED_MD5,
    EXPECTED_SIZE,
    HEIGHT,
    OUTPUT_BYTES,
    VALUE_COUNT,
    WIDTH,
    decode_image,
    inspect,
)


DATASET_ID = "zenodo_silicon_diffraction_tiff_u16"
SERIES_ID = "silicon_ebsd_detector_u16"
SOURCE_NAME = "Si_pattern1.tif"
OUTPUT_NAME = "Si_pattern1_h1152_w1600_u16le.bin"


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_sources(download_dir: Path) -> tuple[Path, dict[str, object]]:
    source = download_dir / SOURCE_NAME
    metadata = download_dir / "zenodo_record_1450892.json"
    if not source.is_file() or source.stat().st_size != EXPECTED_SIZE or file_hash(source, "md5") != EXPECTED_MD5:
        raise SystemExit("missing or mismatched pinned TIFF source")
    if not metadata.is_file():
        raise SystemExit("missing Zenodo record metadata")
    record = json.loads(metadata.read_text())
    if int(record.get("id", 0)) != 1450892 or record.get("metadata", {}).get("title") != "Silicon Single Crystal Diffraction Pattern":
        raise SystemExit("unexpected Zenodo record identity")
    if record.get("metadata", {}).get("license", {}).get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    report = inspect(source)
    expected_stats = {
        "minimum": 4093,
        "maximum": 65535,
        "distinct_values": 3659,
        "zero_values": 0,
        "saturated_values": 1,
        "flattened_transitions": 1809874,
    }
    for key, expected in expected_stats.items():
        if report.get(key) != expected:
            raise SystemExit(f"unexpected decoded TIFF statistic {key}: {report.get(key)} != {expected}")
    return source, report


def build(args: argparse.Namespace) -> None:
    source, report = validate_sources(args.download_dir)
    family_dir = args.samples_dir / SERIES_ID
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True)
    output = family_dir / OUTPUT_NAME
    payload, _layout = decode_image(source)
    output.write_bytes(payload)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": output.relative_to(args.data_root).as_posix(),
        "source_sample": source.relative_to(args.data_root).as_posix(),
        "source_file": source.name,
        "value_count": VALUE_COUNT,
        "sample_size_bytes": OUTPUT_BYTES,
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "sample_geometry": "2d_ebsd_diffraction_pattern",
        "sample_shape": [HEIGHT, WIDTH],
        "sample_axes": ["detector_y", "detector_x"],
        "natural_record_kind": "ebsd_detector_frame",
        "minimum": report["minimum"],
        "maximum": report["maximum"],
        "distinct_values": report["distinct_values"],
        "sha256": payload_sha256,
    }
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": 1,
        "value_count": VALUE_COUNT,
        "total_size_bytes": OUTPUT_BYTES,
        "payload_sha256": payload_sha256,
        "source_inspection": report,
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "sample_count": 1,
        "value_count": VALUE_COUNT,
        "total_size_bytes": OUTPUT_BYTES,
        "payload_sha256": payload_sha256,
        "minimum": report["minimum"],
        "maximum": report["maximum"],
        "distinct_values": report["distinct_values"],
    }, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    source, _report = validate_sources(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if len(rows) != 1:
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    row = rows[0]
    expected, _layout = decode_image(source)
    output = args.data_root / str(row["sample_path"])
    if not output.is_file() or output.read_bytes() != expected:
        raise SystemExit("output does not match independently decoded TIFF detector words")
    output_sha256 = hashlib.sha256(expected).hexdigest()
    if row.get("sha256") != output_sha256:
        raise SystemExit("indexed output hash mismatch")
    if int(row["value_count"]) != VALUE_COUNT or int(row["sample_size_bytes"]) != OUTPUT_BYTES:
        raise SystemExit("indexed value/byte totals are incorrect")
    actual_outputs = {path.resolve() for path in args.data_root.joinpath("samples", DATASET_ID).glob("*/*.bin")}
    if actual_outputs != {output.resolve()}:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text())
    if stats.get("sample_count") != 1 or stats.get("value_count") != VALUE_COUNT or stats.get("total_size_bytes") != OUTPUT_BYTES:
        raise SystemExit("ingest stats do not match verified totals")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": 1,
        "verified_values": VALUE_COUNT,
        "verified_bytes": OUTPUT_BYTES,
        "payload_sha256": output_sha256,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
