#!/usr/bin/env python3
"""Build and verify the native uint16 Venere ENVI detector tensor."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from inspect_envi_u16 import (
    BANDS,
    HEADER_MD5,
    HEADER_SIZE,
    LINES,
    PAYLOAD_MD5,
    PAYLOAD_SIZE,
    SAMPLES,
    VALUE_COUNT,
    inspect,
)


DATASET_ID = "zenodo_venere_nir_hsi_u16"
SERIES_ID = "venere_nir_hsi_detector_u16"
HEADER_NAME = "venere.hdr"
PAYLOAD_NAME = "venere.raw"
OUTPUT_NAME = "venere_l410_b288_s384_bil_u16le.bin"


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_sources(download_dir: Path) -> tuple[Path, Path, dict[str, object]]:
    header = download_dir / HEADER_NAME
    payload = download_dir / PAYLOAD_NAME
    metadata = download_dir / "zenodo_record_8143550.json"
    if not header.is_file() or header.stat().st_size != HEADER_SIZE or file_hash(header, "md5") != HEADER_MD5:
        raise SystemExit("missing or mismatched pinned ENVI header")
    if not payload.is_file() or payload.stat().st_size != PAYLOAD_SIZE or file_hash(payload, "md5") != PAYLOAD_MD5:
        raise SystemExit("missing or mismatched pinned ENVI payload")
    if not metadata.is_file():
        raise SystemExit("missing Zenodo record metadata")
    record = json.loads(metadata.read_text())
    expected_title = 'Push-broom NIR-HSI scanning of painting reconstruction, inspired by Sandro Botticelli\'s "Venus"'
    if int(record.get("id", 0)) != 8143550 or record.get("metadata", {}).get("title") != expected_title:
        raise SystemExit("unexpected Zenodo record identity")
    if record.get("metadata", {}).get("license", {}).get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    report = inspect(header, payload)
    expected_stats = {
        "minimum": 5501,
        "maximum": 65535,
        "distinct_values": 47423,
        "zero_values": 0,
        "saturated_values": 46,
        "constant_bands": 0,
    }
    for key, expected in expected_stats.items():
        if report.get(key) != expected:
            raise SystemExit(f"unexpected ENVI statistic {key}: {report.get(key)} != {expected}")
    return header, payload, report


def emit_elements(payload: Path, output: Path) -> None:
    with payload.open("rb") as source, output.open("wb") as target:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            if len(block) % 2:
                raise SystemExit("ENVI payload block ends inside a uint16 element")
            target.write(block)
    if output.stat().st_size != PAYLOAD_SIZE:
        raise SystemExit("emitted ENVI element stream has an unexpected size")


def build(args: argparse.Namespace) -> None:
    _header, payload, report = validate_sources(args.download_dir)
    family_dir = args.samples_dir / SERIES_ID
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True)
    output = family_dir / OUTPUT_NAME
    emit_elements(payload, output)
    payload_sha256 = file_hash(output, "sha256")
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": output.relative_to(args.data_root).as_posix(),
        "source_sample": payload.relative_to(args.data_root).as_posix(),
        "source_file": payload.name,
        "value_count": VALUE_COUNT,
        "sample_size_bytes": PAYLOAD_SIZE,
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "sample_geometry": "3d_hyperspectral_bil_cube",
        "sample_shape": [LINES, BANDS, SAMPLES],
        "sample_axes": ["scan_line", "spectral_band", "spatial_sample"],
        "natural_record_kind": "envi_hyperspectral_cube",
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
        "total_size_bytes": PAYLOAD_SIZE,
        "payload_sha256": payload_sha256,
        "source_inspection": report,
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "sample_count": 1,
        "value_count": VALUE_COUNT,
        "total_size_bytes": PAYLOAD_SIZE,
        "payload_sha256": payload_sha256,
        "minimum": report["minimum"],
        "maximum": report["maximum"],
        "distinct_values": report["distinct_values"],
    }, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    _header, payload, _report = validate_sources(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if len(rows) != 1:
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    row = rows[0]
    output = args.data_root / str(row["sample_path"])
    if not output.is_file() or output.stat().st_size != PAYLOAD_SIZE:
        raise SystemExit("missing or incorrectly sized output cube")
    source_sha256 = file_hash(payload, "sha256")
    output_sha256 = file_hash(output, "sha256")
    if source_sha256 != output_sha256 or row.get("sha256") != output_sha256:
        raise SystemExit("source/output/index cube hash mismatch")
    if int(row["value_count"]) != VALUE_COUNT or int(row["sample_size_bytes"]) != PAYLOAD_SIZE:
        raise SystemExit("indexed value/byte totals are incorrect")
    actual_outputs = {path.resolve() for path in args.data_root.joinpath("samples", DATASET_ID).glob("*/*.bin")}
    if actual_outputs != {output.resolve()}:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text())
    if stats.get("sample_count") != 1 or stats.get("value_count") != VALUE_COUNT or stats.get("total_size_bytes") != PAYLOAD_SIZE:
        raise SystemExit("ingest stats do not match verified totals")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": 1,
        "verified_values": VALUE_COUNT,
        "verified_bytes": PAYLOAD_SIZE,
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
