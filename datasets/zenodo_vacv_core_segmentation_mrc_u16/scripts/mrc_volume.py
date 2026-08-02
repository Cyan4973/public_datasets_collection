#!/usr/bin/env python3
"""Build and verify one byte-preserved native uint16 segmentation volume."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from inspect_mrc_u16 import EXPECTED_MD5, EXPECTED_SIZE, inspect


DATASET_ID = "zenodo_vacv_core_segmentation_mrc_u16"
SERIES_ID = "vacv_core_segmentation_volume_u16"
SOURCE_NAME = "032_original_ground_truth.mrc"
OUTPUT_NAME = "032_original_ground_truth_250x464x464_u16le.bin"
DATA_OFFSET = 1024
VALUE_COUNT = 53_824_000
OUTPUT_BYTES = VALUE_COUNT * 2


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_sources(download_dir: Path) -> tuple[Path, dict[str, object]]:
    source = download_dir / SOURCE_NAME
    metadata = download_dir / "zenodo_record_20262954.json"
    if not source.is_file() or source.stat().st_size != EXPECTED_SIZE or file_hash(source, "md5") != EXPECTED_MD5:
        raise SystemExit("missing or mismatched pinned MRC source")
    if not metadata.is_file():
        raise SystemExit("missing Zenodo record metadata")
    record = json.loads(metadata.read_text())
    if int(record.get("id", 0)) != 20262954:
        raise SystemExit("unexpected Zenodo record id")
    if record.get("metadata", {}).get("title") != "3D segmentation for VACV cores":
        raise SystemExit("unexpected Zenodo record title")
    if record.get("metadata", {}).get("license", {}).get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    report = inspect(source)
    if report.get("histogram") != {"0": 52_401_944, "255": 1_422_056}:
        raise SystemExit("unexpected segmentation label histogram")
    return source, report


def copy_payload(source: Path, output: Path) -> None:
    with source.open("rb") as src, output.open("wb") as dst:
        src.seek(DATA_OFFSET)
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    if output.stat().st_size != OUTPUT_BYTES:
        raise SystemExit("unexpected copied voxel payload size")


def build(args: argparse.Namespace) -> None:
    source, report = validate_sources(args.download_dir)
    family_dir = args.samples_dir / SERIES_ID
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True)
    output = family_dir / OUTPUT_NAME
    copy_payload(source, output)
    payload_sha256 = file_hash(output, "sha256")
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": output.relative_to(args.data_root).as_posix(),
        "source_sample": source.relative_to(args.data_root).as_posix(),
        "source_file": source.name,
        "source_payload_offset": DATA_OFFSET,
        "value_count": VALUE_COUNT,
        "sample_size_bytes": OUTPUT_BYTES,
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "sample_geometry": "3d_segmentation_volume",
        "sample_shape": [250, 464, 464],
        "sample_axes": ["z", "y", "x"],
        "natural_record_kind": "mrc_volume",
        "minimum": 0,
        "maximum": 255,
        "distinct_values": 2,
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
    print(json.dumps(stats, indent=2, sort_keys=True))


def source_payload_hash(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        handle.seek(DATA_OFFSET)
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(args: argparse.Namespace) -> None:
    source, _ = validate_sources(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if len(rows) != 1:
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    row = rows[0]
    output = args.data_root / str(row["sample_path"])
    if not output.is_file() or output.stat().st_size != OUTPUT_BYTES:
        raise SystemExit("missing or incorrectly sized output payload")
    source_sha256 = source_payload_hash(source)
    output_sha256 = file_hash(output, "sha256")
    if source_sha256 != output_sha256 or row.get("sha256") != output_sha256:
        raise SystemExit("source/output/index payload hash mismatch")
    if int(row["value_count"]) != VALUE_COUNT or int(row["sample_size_bytes"]) != OUTPUT_BYTES:
        raise SystemExit("indexed value/byte totals are incorrect")
    expected_outputs = {output.resolve()}
    actual_outputs = {path.resolve() for path in args.data_root.joinpath("samples", DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
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
