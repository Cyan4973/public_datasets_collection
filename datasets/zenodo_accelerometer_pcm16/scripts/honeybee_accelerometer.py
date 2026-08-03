#!/usr/bin/env python3
"""Validate and segment the pinned honeybee accelerometer PCM16 WAV."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import struct
import sys


DATASET_ID = "zenodo_accelerometer_pcm16"
SERIES_ID = "honeybee_accelerometer_pcm16"
SOURCE_NAME = "D 18.wav"
SOURCE_BYTES = 5_760_044
SOURCE_MD5 = "118ac1ee5a3ff3bc491b3103b06119b9"
DATA_OFFSET = 44
DATA_BYTES = 5_760_000
SAMPLE_RATE = 48_000
SEGMENT_COUNT = 60
VALUES_PER_SEGMENT = SAMPLE_RATE
BYTES_PER_SEGMENT = VALUES_PER_SEGMENT * 2
VALUE_COUNT = SEGMENT_COUNT * VALUES_PER_SEGMENT
PAYLOAD_SHA256 = "8ddb9ca05969ce97469a88819854977e7e1e27f786c73dcda8345f7ee7adb775"
EXPECTED_AGGREGATE = {
    "minimum": -874,
    "maximum": 873,
    "distinct_values": 1547,
    "zero_values": 108606,
    "transitions": 2767201,
}


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_metadata(download_dir: Path) -> None:
    path = download_dir / "zenodo_record_7018660.json"
    if not path.is_file():
        raise ValueError("missing Zenodo record metadata")
    record = json.loads(path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    license_obj = metadata.get("license", {}) if isinstance(metadata, dict) else {}
    if (
        int(record.get("id", 0)) != 7018660
        or metadata.get("title") != "Audio D18"
        or not isinstance(license_obj, dict)
        or license_obj.get("id") != "cc-by-4.0"
    ):
        raise ValueError("unexpected Zenodo record identity, title, or license")
    description = html.unescape(re.sub(r"<[^>]+>", " ", str(metadata.get("description", ""))))
    description = re.sub(r"\s+", " ", description).strip().lower()
    required = (
        "accelerometer data",
        "honeybee vibrations",
        "60 points",
        "one point on the df space plot = one second accelerometer data",
    )
    if any(text not in description for text in required):
        raise ValueError("record description no longer documents the expected segmentation")


def decode_source(download_dir: Path) -> tuple[list[bytes], dict[str, object]]:
    validate_metadata(download_dir)
    path = download_dir / SOURCE_NAME
    if not path.is_file() or path.stat().st_size != SOURCE_BYTES or file_hash(path, "md5") != SOURCE_MD5:
        raise ValueError("missing or changed WAV source")
    data = path.read_bytes()
    if data[:12] != b"RIFF\x24\xe4\x57\x00WAVE":
        raise ValueError("unexpected RIFF/WAVE header or size")
    if data[12:20] != b"fmt \x10\x00\x00\x00":
        raise ValueError("expected a canonical 16-byte fmt chunk")
    fmt = struct.unpack_from("<HHIIHH", data, 20)
    if fmt != (1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16):
        raise ValueError(f"unexpected PCM format declaration: {fmt}")
    if data[36:40] != b"data" or struct.unpack_from("<I", data, 40)[0] != DATA_BYTES:
        raise ValueError("unexpected WAVE data chunk")
    payload = data[DATA_OFFSET:]
    if len(payload) != DATA_BYTES or hashlib.sha256(payload).hexdigest() != PAYLOAD_SHA256:
        raise ValueError("PCM payload size or SHA-256 changed")
    segments = [
        payload[index * BYTES_PER_SEGMENT : (index + 1) * BYTES_PER_SEGMENT]
        for index in range(SEGMENT_COUNT)
    ]
    if len(segments) != SEGMENT_COUNT or any(len(segment) != BYTES_PER_SEGMENT for segment in segments):
        raise ValueError("PCM payload does not split into 60 exact one-second segments")
    values = array("h")
    values.frombytes(payload)
    if values.itemsize != 2:
        raise ValueError("host signed-short width is not 16 bits")
    if sys.byteorder == "big":
        values.byteswap()
    aggregate = {
        "minimum": min(values),
        "maximum": max(values),
        "distinct_values": len(set(values)),
        "zero_values": values.count(0),
        "transitions": sum(left != right for left, right in zip(values, values[1:])),
    }
    if aggregate != EXPECTED_AGGREGATE:
        raise ValueError(f"aggregate PCM statistics changed: {aggregate}")
    segment_reports = []
    for index, segment in enumerate(segments):
        segment_values = array("h")
        segment_values.frombytes(segment)
        if sys.byteorder == "big":
            segment_values.byteswap()
        distinct = len(set(segment_values))
        if distinct < 200 or max(segment_values) == min(segment_values):
            raise ValueError(f"segment {index} is unexpectedly degenerate")
        segment_reports.append({
            "segment_index": index,
            "source_frame_start": index * VALUES_PER_SEGMENT,
            "sample_rate_hz": SAMPLE_RATE,
            "duration_seconds": 1,
            "value_count": VALUES_PER_SEGMENT,
            "decoded_bytes": BYTES_PER_SEGMENT,
            "minimum": min(segment_values),
            "maximum": max(segment_values),
            "distinct_values": distinct,
            "zero_values": segment_values.count(0),
            "transitions": sum(
                left != right for left, right in zip(segment_values, segment_values[1:])
            ),
            "decoded_sha256": hashlib.sha256(segment).hexdigest(),
        })
    report = {
        "source_file": SOURCE_NAME,
        "source_bytes": SOURCE_BYTES,
        "source_md5": SOURCE_MD5,
        "audio_format": "PCM",
        "channels": 1,
        "sample_rate_hz": SAMPLE_RATE,
        "bits_per_sample": 16,
        "data_offset": DATA_OFFSET,
        "data_bytes": DATA_BYTES,
        "payload_sha256": PAYLOAD_SHA256,
        "segment_count": SEGMENT_COUNT,
        "values_per_segment": VALUES_PER_SEGMENT,
        "value_count": VALUE_COUNT,
        **aggregate,
        "segments": segment_reports,
    }
    return segments, report


def inspect_command(args: argparse.Namespace) -> None:
    _segments, report = decode_source(args.download_dir)
    result = {
        "dataset_id": DATASET_ID,
        "sample_count": SEGMENT_COUNT,
        "value_count": VALUE_COUNT,
        "total_size_bytes": DATA_BYTES,
        "aggregate_payload_sha256": PAYLOAD_SHA256,
        "source_inspection": report,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "sample_count": SEGMENT_COUNT,
        "value_count": VALUE_COUNT,
        "total_size_bytes": DATA_BYTES,
        "minimum": report["minimum"],
        "maximum": report["maximum"],
        "distinct_values": report["distinct_values"],
        "aggregate_payload_sha256": PAYLOAD_SHA256,
    }, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    segments, report = decode_source(args.download_dir)
    family_dir = args.samples_dir / SERIES_ID
    if family_dir.exists():
        shutil.rmtree(family_dir)
    family_dir.mkdir(parents=True)
    source = args.download_dir / SOURCE_NAME
    rows = []
    for segment, segment_report in zip(segments, report["segments"]):
        index = int(segment_report["segment_index"])
        output = family_dir / f"honeybee_vibration_{index:03d}_n{VALUES_PER_SEGMENT}_i16le.bin"
        output.write_bytes(segment)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": source.relative_to(args.data_root).as_posix(),
            "source_file": SOURCE_NAME,
            "segment_index": index,
            "source_frame_start": segment_report["source_frame_start"],
            "value_count": VALUES_PER_SEGMENT,
            "sample_size_bytes": BYTES_PER_SEGMENT,
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "sample_geometry": "1d_accelerometer_vibration_segment",
            "sample_shape": [VALUES_PER_SEGMENT],
            "sample_axes": ["time_sample"],
            "natural_record_kind": "one_second_accelerometer_point",
            "sample_rate_hz": SAMPLE_RATE,
            "minimum": segment_report["minimum"],
            "maximum": segment_report["maximum"],
            "distinct_values": segment_report["distinct_values"],
            "sha256": segment_report["decoded_sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": SEGMENT_COUNT,
        "value_count": VALUE_COUNT,
        "total_size_bytes": DATA_BYTES,
        "aggregate_payload_sha256": PAYLOAD_SHA256,
        "source_inspection": report,
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: stats[key] for key in (
        "dataset_id", "sample_count", "value_count", "total_size_bytes",
        "aggregate_payload_sha256",
    )}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    segments, _report = decode_source(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    if len(rows) != SEGMENT_COUNT:
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs = set()
    aggregate = hashlib.sha256()
    for index, (row, segment) in enumerate(zip(rows, segments)):
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if (
            row.get("segment_index") != index
            or row.get("sample_shape") != [VALUES_PER_SEGMENT]
            or not output.is_file()
            or output.read_bytes() != segment
        ):
            raise SystemExit(f"output mismatch for segment {index}")
        if row.get("sha256") != hashlib.sha256(segment).hexdigest():
            raise SystemExit(f"indexed hash mismatch for segment {index}")
        aggregate.update(segment)
    actual_outputs = {
        path.resolve()
        for path in args.data_root.joinpath("samples", DATASET_ID).glob("*/*.bin")
    }
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stats = json.loads(args.stats.read_text())
    if (
        stats.get("sample_count") != SEGMENT_COUNT
        or stats.get("value_count") != VALUE_COUNT
        or stats.get("total_size_bytes") != DATA_BYTES
        or stats.get("aggregate_payload_sha256") != PAYLOAD_SHA256
        or aggregate.hexdigest() != PAYLOAD_SHA256
    ):
        raise SystemExit("ingest stats do not match verified totals")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": SEGMENT_COUNT,
        "verified_values": VALUE_COUNT,
        "verified_bytes": DATA_BYTES,
        "aggregate_payload_sha256": aggregate.hexdigest(),
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
