#!/usr/bin/env python3
"""Preflight, build, and verify UCI raw signed-int8 sEMG recordings."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import html
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import statistics
import zipfile


DATASET_ID = "uci_emg_gestures_i8"
SERIES_ID = "semg_channel_i8"
CHANNEL_COUNT = 8
MIN_RECORDINGS = 50
MAX_RECORDINGS = 100
MIN_VALUES_PER_CHANNEL = 1_000
MIN_TOTAL_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000
MAX_TOTAL_BYTES = 1_000_000_000
TABLE_SUFFIXES = {".txt", ".csv", ".tsv"}
SOURCE_DECIMAL_SCALE = Decimal("100000")
EXPECTED_IDENTITIES = {
    "archive": (17699840, "e82247b6478e5a1c5ad621c1f2cc1bb878547c51f01f4e6226abb2a4819ce4ee"),
    "metadata": (2728, "6a8ef398d1eacd881db91e5217a31d734669e21d891bfe3d7ee5d20fd501190e"),
    "rights": (111120, "665c037969f6df4f86b77150af2e045e19a64c617dd1d89d261e6ea963d586f2"),
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_identity(path: Path, identity: str) -> None:
    expected_size, expected_hash = EXPECTED_IDENTITIES[identity]
    if not path.is_file():
        raise SystemExit(f"missing {identity}: {path}")
    actual_size = path.stat().st_size
    actual_hash = file_hash(path)
    if actual_size != expected_size or actual_hash != expected_hash:
        raise SystemExit(
            f"{identity} identity mismatch: size={actual_size} sha256={actual_hash}"
        )


def validate_metadata(path: Path) -> dict[str, object]:
    validate_identity(path, "metadata")
    data = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(data, ensure_ascii=False).lower()
    if "emg data for gestures" not in text or not re.search(r'"uci_id"\s*:\s*481', text):
        raise SystemExit("UCI metadata does not identify EMG Data for Gestures dataset 481")
    return data


def validate_rights(path: Path) -> None:
    validate_identity(path, "rights")
    text = html.unescape(path.read_text(encoding="utf-8", errors="replace")).lower()
    text = re.sub(r"\s+", " ", text)
    if "emg data for gestures" not in text:
        raise SystemExit("official UCI rights-page identity validation failed")
    if not any(term in text for term in ("cc by 4.0", "cc-by-4.0", "creative commons attribution 4.0", "creativecommons.org/licenses/by/4.0")):
        raise SystemExit("official UCI page lacks CC BY 4.0 evidence")


def decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "ascii", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text:
            return text
    raise ValueError("unsupported text encoding or binary table")


def split_fields(line: str, delimiter: str) -> list[str]:
    if delimiter == "whitespace":
        return line.strip().split()
    return next(csv.reader([line], delimiter=delimiter))


def choose_delimiter(lines: list[str]) -> str:
    candidates = ("\t", ";", ",", "whitespace")
    scores: list[tuple[int, str]] = []
    for delimiter in candidates:
        widths = []
        try:
            for line in lines[:20]:
                widths.append(len(split_fields(line, delimiter)))
        except csv.Error:
            continue
        scores.append((sum(width == 10 for width in widths), delimiter))
    if not scores or max(score for score, _ in scores) == 0:
        raise ValueError("cannot identify a ten-column delimiter")
    return max(scores, key=lambda item: (item[0], item[1] != "whitespace"))[1]


def integer(value: str) -> int | None:
    text = value.strip()
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        return None
    return int(text)


def scaled_int8(value: str) -> int | None:
    """Exactly invert UCI's 1e-5 decimal storage of the Myo int8 code."""
    try:
        scaled = Decimal(value.strip()) * SOURCE_DECIMAL_SCALE
    except InvalidOperation:
        return None
    integral = scaled.to_integral_value()
    if scaled != integral:
        return None
    result = int(integral)
    return result if -128 <= result <= 127 else None


def recording_slug(index: int, member: str) -> str:
    stem = str(PurePosixPath(member).with_suffix(""))
    normalized = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")[-80:]
    suffix = hashlib.sha256(member.encode("utf-8")).hexdigest()[:8]
    return f"recording_{index:03d}_{normalized}_{suffix}"


def parse_recording(raw: bytes, member: str) -> tuple[list[bytes], dict[str, object]]:
    text = decode_text(raw)
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < MIN_VALUES_PER_CHANNEL:
        raise ValueError(f"too few nonempty rows: {len(lines)}")
    delimiter = choose_delimiter(lines)
    first = [field.strip() for field in split_fields(lines[0], delimiter)]
    if len(first) != 10:
        raise ValueError(f"first row has {len(first)} fields")
    first_channels = [scaled_int8(value) for value in first[1:9]]
    data_start = 0 if all(value is not None for value in first_channels) and integer(first[9]) is not None else 1
    if data_start == 1 and len(lines) - 1 < MIN_VALUES_PER_CHANNEL:
        raise ValueError("header leaves too few data rows")

    channels = [bytearray() for _ in range(CHANNEL_COUNT)]
    labels: Counter[int] = Counter()
    first_time: float | None = None
    previous_time: float | None = None
    last_time: float | None = None
    for row_index, line in enumerate(lines[data_start:], data_start + 1):
        fields = [field.strip() for field in split_fields(line, delimiter)]
        if len(fields) != 10:
            raise ValueError(f"row {row_index} has {len(fields)} fields")
        try:
            time_value = float(fields[0])
        except ValueError as exc:
            raise ValueError(f"nonnumeric time at row {row_index}") from exc
        if not math.isfinite(time_value):
            raise ValueError(f"nonfinite time at row {row_index}")
        if previous_time is not None and time_value < previous_time:
            raise ValueError(f"backward time at row {row_index}")
        values = [scaled_int8(value) for value in fields[1:9]]
        if any(value is None for value in values):
            raise ValueError(f"channel is not an exact 1e-5-scaled signed-int8 code at row {row_index}: {fields[1:9]}")
        label = integer(fields[9])
        if label is None or not 0 <= label <= 255:
            raise ValueError(f"gesture label outside uint8 at row {row_index}: {fields[9]!r}")
        for channel, value in zip(channels, values, strict=True):
            channel.append(int(value) & 0xFF)
        labels[label] += 1
        if first_time is None:
            first_time = time_value
        previous_time = time_value
        last_time = time_value
    payloads = [bytes(channel) for channel in channels]
    if any(len(payload) < MIN_VALUES_PER_CHANNEL or len(set(payload)) < 2 for payload in payloads):
        raise ValueError("short or constant EMG channel")
    return payloads, {
        "source_member": member,
        "source_size_bytes": len(raw),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "delimiter": "tab" if delimiter == "\t" else delimiter,
        "has_header": bool(data_start),
        "row_count": len(payloads[0]),
        "first_time": first_time,
        "last_time": last_time,
        "gesture_histogram": {str(key): labels[key] for key in sorted(labels)},
        "source_decimal_scale": 100000,
    }


def scan_archive(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    validate_identity(path, "archive")
    if not zipfile.is_zipfile(path):
        raise SystemExit(f"missing or invalid source archive: {path}")
    recordings: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"ZIP CRC failure: {bad}")
        total_uncompressed = 0
        candidates: list[zipfile.ZipInfo] = []
        for info in archive.infolist():
            member_path = PurePosixPath(info.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise SystemExit(f"unsafe ZIP member: {info.filename}")
            if info.flag_bits & 1:
                raise SystemExit(f"encrypted ZIP member: {info.filename}")
            total_uncompressed += info.file_size
            if total_uncompressed > 1_000_000_000:
                raise SystemExit("uncompressed archive exceeds 1 GB")
            if not info.is_dir() and member_path.suffix.lower() in TABLE_SUFFIXES and info.file_size >= 100:
                candidates.append(info)
        candidates.sort(key=lambda info: info.filename)
        for info in candidates:
            raw = archive.read(info)
            try:
                payloads, metadata = parse_recording(raw, info.filename)
            except ValueError as exc:
                rejected.append({"source_member": info.filename, "size_bytes": info.file_size, "reason": str(exc)})
                continue
            recordings.append({"payloads": payloads, "metadata": metadata})
    if not MIN_RECORDINGS <= len(recordings) <= MAX_RECORDINGS:
        raise SystemExit(f"recording coverage outside bounds: {len(recordings)}; rejected={rejected[:20]}")
    total_values = sum(len(recording["payloads"][0]) * CHANNEL_COUNT for recording in recordings)
    sample_lengths = [len(payload) for recording in recordings for payload in recording["payloads"]]
    if total_values < MIN_TOTAL_VALUES or statistics.median(sample_lengths) < MIN_MEDIAN_VALUES:
        raise SystemExit("EMG primary payload does not meet acceptance floors")
    hashes: set[str] = set()
    for recording in recordings:
        for payload in recording["payloads"]:
            digest = hashlib.sha256(payload).hexdigest()
            if digest in hashes:
                raise SystemExit("duplicate EMG channel payload")
            hashes.add(digest)
    return recordings, rejected


def make_summary(recordings: list[dict[str, object]], rejected: list[dict[str, object]]) -> dict[str, object]:
    lengths = [len(payload) for recording in recordings for payload in recording["payloads"]]
    total = sum(lengths)
    if total > MAX_TOTAL_BYTES:
        raise SystemExit("decoded EMG payload exceeds 1 GB")
    profiles = []
    for recording_index, recording in enumerate(recordings):
        metadata = dict(recording["metadata"])
        metadata["recording_index"] = recording_index
        metadata["channels"] = [
            {
                "channel_index": channel_index,
                "minimum": min(value - 256 if value >= 128 else value for value in payload),
                "maximum": max(value - 256 if value >= 128 else value for value in payload),
                "distinct_values": len(set(payload)),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for channel_index, payload in enumerate(recording["payloads"], 1)
        ]
        profiles.append(metadata)
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "recording_count": len(recordings),
        "sample_count": len(lengths),
        "value_count": total,
        "total_size_bytes": total,
        "source_decimal_scale": 100000,
        "median_sample_value_count": statistics.median(lengths),
        "minimum_sample_value_count": min(lengths),
        "maximum_sample_value_count": max(lengths),
        "rejected_table_members": rejected,
        "recordings": profiles,
    }


def preflight(args: argparse.Namespace) -> None:
    metadata = validate_metadata(args.metadata)
    validate_rights(args.rights)
    recordings, rejected = scan_archive(args.archive)
    result = {
        **make_summary(recordings, rejected),
        "uci_dataset_id": 481,
        "license": "CC BY 4.0",
        "archive_size_bytes": args.archive.stat().st_size,
        "archive_sha256": file_hash(args.archive),
        "metadata_size_bytes": args.metadata.stat().st_size,
        "metadata_sha256": file_hash(args.metadata),
        "rights_size_bytes": args.rights.stat().st_size,
        "rights_sha256": file_hash(args.rights),
        "metadata_identity_valid": bool(metadata),
    }
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "recordings"}, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    recordings, rejected = scan_archive(args.archive)
    series_dir = args.samples_dir / SERIES_ID
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for recording_index, recording in enumerate(recordings):
        metadata = recording["metadata"]
        slug = recording_slug(recording_index, str(metadata["source_member"]))
        for channel_index, payload in enumerate(recording["payloads"], 1):
            output = series_dir / f"{slug}_ch{channel_index:02d}_i8_n{len(payload)}.bin"
            output.write_bytes(payload)
            signed_values = [value - 256 if value >= 128 else value for value in payload]
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "source_sample": args.archive.relative_to(args.data_root).as_posix(),
                "source_member": metadata["source_member"],
                "source_member_sha256": metadata["source_sha256"],
                "recording_index": recording_index,
                "channel_index": channel_index,
                "source_field": f"raw EMG channel {channel_index}",
                "numeric_kind": "int",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "value_count": len(payload),
                "sample_size_bytes": len(payload),
                "sample_format": "raw homogeneous signed-int8 surface-EMG timeline",
                "sample_geometry": "semg_recording_channel_time_series_1d",
                "sample_rank": 1,
                "sample_shape": [len(payload)],
                "sample_axes": ["observation_time"],
                "natural_record_kind": "complete_semg_recording_channel_timeline",
                "minimum": min(signed_values),
                "maximum": max(signed_values),
                "distinct_values": len(set(payload)),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    result = make_summary(recordings, rejected)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "recordings"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    recordings, rejected = scan_archive(args.archive)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_samples = sum(len(recording["payloads"]) for recording in recordings)
    if len(rows) != expected_samples:
        raise SystemExit("index row count differs from decoded channel count")
    expected_outputs: set[Path] = set()
    cursor = 0
    for recording_index, recording in enumerate(recordings):
        metadata = recording["metadata"]
        for channel_index, payload in enumerate(recording["payloads"], 1):
            row = rows[cursor]
            cursor += 1
            if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
                raise SystemExit("dataset/series/role mismatch")
            if row.get("source_member") != metadata["source_member"] or row.get("recording_index") != recording_index or row.get("channel_index") != channel_index:
                raise SystemExit("source recording/channel ordering mismatch")
            if row.get("numeric_kind") != "int" or row.get("bit_width") != 8 or row.get("endianness") != "little" or row.get("element_size_bytes") != 1:
                raise SystemExit("numeric schema mismatch")
            if row.get("value_count") != len(payload) or row.get("sample_size_bytes") != len(payload):
                raise SystemExit("sample size mismatch")
            output = args.data_root / str(row["sample_path"])
            if not output.is_file() or output.read_bytes() != payload:
                raise SystemExit(f"output differs from fresh archive parse: {output}")
            if row.get("sha256") != hashlib.sha256(payload).hexdigest():
                raise SystemExit(f"indexed hash mismatch: {output}")
            expected_outputs.add(output.resolve())
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    expected_summary = make_summary(recordings, rejected)
    if json.loads(args.stats.read_text(encoding="utf-8")) != expected_summary:
        raise SystemExit("ingest stats differ from fresh archive parse")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_recordings": len(recordings),
        "verified_samples": len(rows),
        "verified_values": expected_summary["value_count"],
        "verified_bytes": expected_summary["total_size_bytes"],
        "median_sample_value_count": expected_summary["median_sample_value_count"],
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--archive", type=Path, required=True)
    preflight_parser.add_argument("--metadata", type=Path, required=True)
    preflight_parser.add_argument("--rights", type=Path, required=True)
    preflight_parser.add_argument("--profile", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--archive", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
