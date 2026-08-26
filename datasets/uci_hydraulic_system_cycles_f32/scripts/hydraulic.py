#!/usr/bin/env python3
"""Preflight, build, and verify UCI hydraulic-system 100 Hz cycles."""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import statistics
import struct
from typing import Callable, Iterator
import zipfile


DATASET_ID = "uci_hydraulic_system_cycles_f32"
SERIES_ID = "hydraulic_100hz_cycle_f32"
SENSORS = ("PS1", "PS2", "PS3", "PS4", "PS5", "PS6", "EPS1")
EXPECTED_CYCLES = 2_205
VALUES_PER_CYCLE = 6_000
EXPECTED_SOURCE_SAMPLES = len(SENSORS) * EXPECTED_CYCLES
EXPECTED_CONSTANT_CYCLES = 1_238
EXPECTED_SAMPLES = EXPECTED_SOURCE_SAMPLES - EXPECTED_CONSTANT_CYCLES
EXPECTED_VALUES = EXPECTED_SAMPLES * VALUES_PER_CYCLE
EXPECTED_BYTES = EXPECTED_VALUES * 4
MAX_ARCHIVE_BYTES = 1_500_000_000
MAX_UNCOMPRESSED_BYTES = 4_000_000_000
EXPECTED_IDENTITIES = {
    "archive": (
        76_601_704,
        "24128aad2ee45eea7e6b63ebbd9992cdf25d0483a2cebefbfc13bc69079af1f2",
    ),
    "metadata": (
        3_895,
        "7c9ddaacebd5be9ad26cdecc49a4a1161408be213a1a25c0a61ca108f84f750e",
    ),
    "rights": (
        84_168,
        "1d7ba3b546540cfb65560098fd5196c3aacdbdb31bc9ab8ae044a62789a6d1c7",
    ),
}
PayloadConsumer = Callable[[str, int, str, bytes, dict[str, object]], None]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str, max_bytes: int) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise SystemExit(f"{label} size outside bounds: {size}")


def validate_identity(path: Path, identity: str, max_bytes: int) -> None:
    require_file(path, identity, max_bytes)
    expected_size, expected_hash = EXPECTED_IDENTITIES[identity]
    actual_size = path.stat().st_size
    actual_hash = file_hash(path)
    if actual_size != expected_size or actual_hash != expected_hash:
        raise SystemExit(
            f"{identity} identity mismatch: size={actual_size} sha256={actual_hash}"
        )


def license_evidence(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", html.unescape(text)).lower()
    return any(
        term in normalized
        for term in (
            "cc by 4.0",
            "cc-by-4.0",
            "creative commons attribution 4.0",
            "creativecommons.org/licenses/by/4.0",
        )
    )


def validate_metadata(path: Path) -> dict[str, object]:
    validate_identity(path, "metadata", 2_000_000)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid UCI metadata JSON: {exc}") from exc
    text = json.dumps(data, ensure_ascii=False)
    lowered = text.lower()
    if "condition monitoring of hydraulic systems" not in lowered:
        raise SystemExit("UCI metadata title does not identify the hydraulic-system dataset")
    if not re.search(r'"uci_id"\s*:\s*447(?:\D|$)', lowered):
        raise SystemExit("UCI metadata does not identify dataset 447")
    return data


def validate_rights(path: Path) -> None:
    validate_identity(path, "rights", 5_000_000)
    text = path.read_text(encoding="utf-8", errors="replace")
    lowered = html.unescape(text).lower()
    if "condition monitoring of hydraulic systems" not in lowered:
        raise SystemExit("official UCI rights-page identity validation failed")
    if not license_evidence(text):
        raise SystemExit("official UCI dataset page lacks CC BY 4.0 evidence")


def validate_evidence(metadata: Path, rights: Path) -> None:
    validate_metadata(metadata)
    validate_rights(rights)


def locate_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    total_uncompressed = 0
    by_basename: dict[str, list[zipfile.ZipInfo]] = {}
    for info in archive.infolist():
        member = PurePosixPath(info.filename)
        if member.is_absolute() or ".." in member.parts:
            raise SystemExit(f"unsafe ZIP member: {info.filename}")
        if info.flag_bits & 1:
            raise SystemExit(f"encrypted ZIP member: {info.filename}")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise SystemExit("uncompressed archive exceeds 4 GB safety cap")
        if not info.is_dir():
            by_basename.setdefault(member.name.lower(), []).append(info)
    selected: dict[str, zipfile.ZipInfo] = {}
    for sensor in SENSORS:
        matches = by_basename.get(f"{sensor.lower()}.txt", [])
        if len(matches) != 1:
            raise SystemExit(
                f"expected exactly one {sensor}.txt member, found {len(matches)}"
            )
        selected[sensor] = matches[0]
    return selected


def encode_cycle(fields: list[str], sensor: str, cycle_index: int) -> tuple[bytes, float, float, int]:
    if len(fields) != VALUES_PER_CYCLE:
        raise SystemExit(
            f"{sensor} cycle {cycle_index + 1} has {len(fields)} values; "
            f"expected {VALUES_PER_CYCLE}"
        )
    values: list[float] = []
    for column_index, token in enumerate(fields, 1):
        try:
            value = float(token)
        except ValueError as exc:
            raise SystemExit(
                f"{sensor} cycle {cycle_index + 1} column {column_index} is not numeric: {token!r}"
            ) from exc
        if not math.isfinite(value):
            raise SystemExit(
                f"{sensor} cycle {cycle_index + 1} column {column_index} is non-finite"
            )
        values.append(value)
    try:
        payload = struct.pack(f"<{VALUES_PER_CYCLE}f", *values)
    except (OverflowError, struct.error) as exc:
        raise SystemExit(f"{sensor} cycle {cycle_index + 1} overflows float32") from exc
    stored = [item[0] for item in struct.iter_unpack("<f", payload)]
    if any(not math.isfinite(value) for value in stored):
        raise SystemExit(f"{sensor} cycle {cycle_index + 1} becomes non-finite in float32")
    distinct = len({payload[offset : offset + 4] for offset in range(0, len(payload), 4)})
    return payload, min(stored), max(stored), distinct


def iter_cycles(
    archive_path: Path,
) -> Iterator[tuple[str, int, str, bytes, dict[str, object], zipfile.ZipInfo]]:
    validate_identity(archive_path, "archive", MAX_ARCHIVE_BYTES)
    if not zipfile.is_zipfile(archive_path):
        raise SystemExit(f"invalid ZIP archive: {archive_path}")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = locate_members(archive)
            for sensor in SENSORS:
                info = members[sensor]
                with archive.open(info, "r") as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="strict", newline=None)
                    cycle_count = 0
                    for source_line, line in enumerate(text, 1):
                        if not line.strip():
                            raise SystemExit(f"blank row in {info.filename} at source line {source_line}")
                        if cycle_count >= EXPECTED_CYCLES:
                            raise SystemExit(f"{sensor} has more than {EXPECTED_CYCLES} rows")
                        payload, minimum, maximum, distinct = encode_cycle(
                            line.split(), sensor, cycle_count
                        )
                        yield sensor, cycle_count, info.filename, payload, {
                            "minimum": minimum,
                            "maximum": maximum,
                            "distinct_values": distinct,
                        }, info
                        cycle_count += 1
                    if cycle_count != EXPECTED_CYCLES:
                        raise SystemExit(
                            f"{sensor} has {cycle_count} rows; expected {EXPECTED_CYCLES}"
                        )
    except (UnicodeDecodeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise SystemExit(f"cannot decode source archive: {exc}") from exc


def scan_archive(archive_path: Path, consumer: PayloadConsumer | None = None) -> dict[str, object]:
    hashes: set[str] = set()
    sensor_profiles: dict[str, dict[str, object]] = {}
    sample_lengths: list[int] = []
    source_sample_count = 0
    dropped_constant_sample_count = 0
    total_values = 0
    total_bytes = 0
    for sensor, cycle_index, member, payload, metrics, info in iter_cycles(archive_path):
        source_sample_count += 1
        profile = sensor_profiles.setdefault(
            sensor,
            {
                "source_member": member,
                "source_member_size_bytes": info.file_size,
                "source_member_compressed_size_bytes": info.compress_size,
                "source_member_crc32": f"{info.CRC:08x}",
                "source_cycle_count": 0,
                "emitted_cycle_count": 0,
                "dropped_constant_cycle_count": 0,
                "value_count": 0,
                "minimum": None,
                "maximum": None,
                "concatenated_f32_sha256": hashlib.sha256(),
            },
        )
        profile["source_cycle_count"] = int(profile["source_cycle_count"]) + 1
        if int(metrics["distinct_values"]) < 2:
            profile["dropped_constant_cycle_count"] = (
                int(profile["dropped_constant_cycle_count"]) + 1
            )
            dropped_constant_sample_count += 1
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest in hashes:
            raise SystemExit(
                f"duplicate emitted cycle after float32 conversion: {sensor} cycle {cycle_index + 1}"
            )
        hashes.add(digest)
        profile["emitted_cycle_count"] = int(profile["emitted_cycle_count"]) + 1
        profile["value_count"] = int(profile["value_count"]) + VALUES_PER_CYCLE
        profile["minimum"] = (
            float(metrics["minimum"])
            if profile["minimum"] is None
            else min(float(profile["minimum"]), float(metrics["minimum"]))
        )
        profile["maximum"] = (
            float(metrics["maximum"])
            if profile["maximum"] is None
            else max(float(profile["maximum"]), float(metrics["maximum"]))
        )
        profile["concatenated_f32_sha256"].update(payload)
        sample_lengths.append(VALUES_PER_CYCLE)
        total_values += VALUES_PER_CYCLE
        total_bytes += len(payload)
        if consumer is not None:
            consumer(sensor, cycle_index, member, payload, metrics)
    if source_sample_count != EXPECTED_SOURCE_SAMPLES:
        raise SystemExit(
            f"decoded {source_sample_count} source cycles; expected {EXPECTED_SOURCE_SAMPLES}"
        )
    if dropped_constant_sample_count != EXPECTED_CONSTANT_CYCLES:
        raise SystemExit(
            f"found {dropped_constant_sample_count} constant cycles; "
            f"expected {EXPECTED_CONSTANT_CYCLES}"
        )
    if len(sample_lengths) != EXPECTED_SAMPLES:
        raise SystemExit(f"decoded {len(sample_lengths)} samples; expected {EXPECTED_SAMPLES}")
    if total_values != EXPECTED_VALUES or total_bytes != EXPECTED_BYTES:
        raise SystemExit(
            f"decoded totals mismatch: values={total_values} bytes={total_bytes}"
        )
    for profile in sensor_profiles.values():
        profile["concatenated_f32_sha256"] = profile["concatenated_f32_sha256"].hexdigest()
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sensor_count": len(SENSORS),
        "sensors": list(SENSORS),
        "cycles_per_sensor": EXPECTED_CYCLES,
        "values_per_cycle": VALUES_PER_CYCLE,
        "source_sample_count": source_sample_count,
        "dropped_constant_sample_count": dropped_constant_sample_count,
        "sample_count": len(sample_lengths),
        "value_count": total_values,
        "total_size_bytes": total_bytes,
        "minimum_sample_value_count": min(sample_lengths),
        "median_sample_value_count": statistics.median(sample_lengths),
        "maximum_sample_value_count": max(sample_lengths),
        "sensor_profiles": sensor_profiles,
    }


def preflight(args: argparse.Namespace) -> None:
    validate_evidence(args.metadata, args.rights)
    summary = scan_archive(args.archive)
    result = {
        **summary,
        "uci_dataset_id": 447,
        "license": "CC BY 4.0",
        "archive_size_bytes": args.archive.stat().st_size,
        "archive_sha256": file_hash(args.archive),
        "metadata_size_bytes": args.metadata.stat().st_size,
        "metadata_sha256": file_hash(args.metadata),
        "rights_size_bytes": args.rights.stat().st_size,
        "rights_sha256": file_hash(args.rights),
        "excluded_source_families": [
            "FS1", "FS2", "TS1", "TS2", "TS3", "TS4", "VS1", "CE", "CP", "SE",
            "profile condition labels",
        ],
    }
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    printable = {key: value for key, value in result.items() if key != "sensor_profiles"}
    print(json.dumps(printable, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    validate_evidence(args.metadata, args.rights)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    archive_relative = args.archive.relative_to(args.data_root).as_posix()
    index_handle = args.index.open("w", encoding="utf-8")

    def emit(sensor: str, cycle_index: int, member: str, payload: bytes, metrics: dict[str, object]) -> None:
        output = series_dir / f"{sensor.lower()}_cycle_{cycle_index + 1:04d}_f32_n6000.bin"
        output.write_bytes(payload)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": archive_relative,
            "source_member": member,
            "sensor": sensor,
            "cycle_index": cycle_index,
            "source_field": f"{sensor}.txt row {cycle_index + 1}",
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": VALUES_PER_CYCLE,
            "sample_size_bytes": len(payload),
            "sample_format": "raw homogeneous IEEE-754 float32 sensor-cycle time series",
            "sample_geometry": "hydraulic_sensor_operating_cycle_1d",
            "sample_rank": 1,
            "sample_shape": [VALUES_PER_CYCLE],
            "sample_axes": ["time_100hz"],
            "sample_rate_hz": 100,
            "natural_record_kind": "complete_sensor_operating_cycle",
            "minimum": metrics["minimum"],
            "maximum": metrics["maximum"],
            "distinct_values": metrics["distinct_values"],
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        index_handle.write(json.dumps(row, sort_keys=True) + "\n")

    try:
        summary = scan_archive(args.archive, emit)
    finally:
        index_handle.close()
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    printable = {key: value for key, value in summary.items() if key != "sensor_profiles"}
    print(json.dumps(printable, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    validate_evidence(args.metadata, args.rights)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build first")
    rows = (
        json.loads(line)
        for line in args.index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    expected_outputs: set[Path] = set()
    verified_samples = 0

    def compare(sensor: str, cycle_index: int, member: str, payload: bytes, metrics: dict[str, object]) -> None:
        nonlocal verified_samples
        try:
            row = next(rows)
        except StopIteration as exc:
            raise SystemExit("index has fewer rows than source cycles") from exc
        required = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "source_member": member,
            "sensor": sensor,
            "cycle_index": cycle_index,
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": VALUES_PER_CYCLE,
            "sample_size_bytes": len(payload),
            "minimum": metrics["minimum"],
            "maximum": metrics["maximum"],
            "distinct_values": metrics["distinct_values"],
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for key, expected in required.items():
            if row.get(key) != expected:
                raise SystemExit(
                    f"index mismatch for {sensor} cycle {cycle_index + 1}: {key}"
                )
        output = args.data_root / str(row.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh source decode: {output}")
        expected_outputs.add(output.resolve())
        verified_samples += 1

    summary = scan_archive(args.archive, compare)
    try:
        next(rows)
    except StopIteration:
        pass
    else:
        raise SystemExit("index has more rows than source cycles")
    actual_outputs = {
        path.resolve()
        for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")
    }
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    if json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise SystemExit("ingest stats differ from fresh source parse")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": verified_samples,
        "verified_values": summary["value_count"],
        "verified_bytes": summary["total_size_bytes"],
        "median_sample_value_count": summary["median_sample_value_count"],
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
        sub.add_argument("--metadata", type=Path, required=True)
        sub.add_argument("--rights", type=Path, required=True)
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
