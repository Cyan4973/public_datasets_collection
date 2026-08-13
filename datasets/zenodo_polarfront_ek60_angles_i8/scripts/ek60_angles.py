#!/usr/bin/env python3
"""Decode native signed-int8 split-beam angle profiles from one pinned EK60 recording."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import zlib


DATASET_ID = "zenodo_polarfront_ek60_angles_i8"
RECORD_ID = 7473204
RECORD_TITLE = "Split-beam echosounder data from keel-mounted EK60 during PolarFront 2022-05 cruise"
SOURCE_NAME = "PolarFront0522-D20220524-T060111.raw"
SOURCE_SIZE = 45_896_704
SOURCE_MD5 = "944f3af1aea3a51cfa7ef7912dde10ba"
PING_COUNT = 1_147
CHANNEL_FREQUENCIES = ((1, 18_000.0), (2, 38_000.0), (3, 120_000.0))
RANGE_BIN_COUNT = 3_188
PROFILE_COUNT = PING_COUNT * len(CHANNEL_FREQUENCIES)
COMPONENTS = (
    ("alongship", "ek60_ping_channel_alongship_angle_i8", 0),
    ("athwartship", "ek60_ping_channel_athwartship_angle_i8", 1),
)
TOTAL_SAMPLE_COUNT = PROFILE_COUNT * len(COMPONENTS)
TOTAL_VALUE_COUNT = TOTAL_SAMPLE_COUNT * RANGE_BIN_COUNT
TOTAL_SIZE_BYTES = TOTAL_VALUE_COUNT


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_source(download_dir: Path) -> Path:
    metadata_path = download_dir / f"record_{RECORD_ID}.json"
    source = download_dir / SOURCE_NAME
    if not metadata_path.is_file():
        raise SystemExit("missing Zenodo metadata; run download.sh first")
    record = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    if int(record.get("id", 0)) != RECORD_ID or metadata.get("title") != RECORD_TITLE:
        raise SystemExit("unexpected Zenodo record identity")
    if metadata.get("license", {}).get("id") not in ("cc-zero", "cc0-1.0"):
        raise SystemExit("Zenodo record no longer declares CC0")
    description = str(metadata.get("description", "")).lower()
    if "simrad ek60" not in description or "18, 38, and 120 khz" not in description:
        raise SystemExit("record no longer documents the selected EK60 acquisition")
    matching = [item for item in record.get("files", []) if item.get("key") == SOURCE_NAME]
    if len(matching) != 1:
        raise SystemExit("pinned EK60 source is absent or ambiguous")
    item = matching[0]
    if int(item.get("size", 0)) != SOURCE_SIZE or item.get("checksum") != f"md5:{SOURCE_MD5}":
        raise SystemExit("pinned EK60 source identity changed")
    if not source.is_file() or source.stat().st_size != SOURCE_SIZE or file_hash(source, "md5") != SOURCE_MD5:
        raise SystemExit("missing or mismatched pinned EK60 source")
    return source


def raw0_header(raw: bytes, position: int, length: int) -> dict[str, object]:
    payload = position + 16
    if payload + 72 > len(raw):
        raise ValueError("truncated RAW0 header")
    channel, mode = struct.unpack_from("<hh", raw, payload)
    frequency = struct.unpack_from("<f", raw, payload + 8)[0]
    sample_interval = struct.unpack_from("<f", raw, payload + 24)[0]
    sound_velocity = struct.unpack_from("<f", raw, payload + 28)[0]
    sample_offset, count = struct.unpack_from("<ii", raw, payload + 64)
    if mode != 3 or (channel, frequency) not in CHANNEL_FREQUENCIES:
        raise ValueError(f"unexpected RAW0 channel/mode/frequency: {channel}/{mode}/{frequency}")
    if sample_offset != 0 or count != RANGE_BIN_COUNT:
        raise ValueError(f"unexpected RAW0 sample offset/count: {sample_offset}/{count}")
    if not math.isfinite(sample_interval) or sample_interval != 0.00025599999935366213:
        raise ValueError(f"unexpected RAW0 sample interval: {sample_interval}")
    if not math.isfinite(sound_velocity) or not 1400.0 <= sound_velocity <= 1550.0:
        raise ValueError(f"unexpected RAW0 sound velocity: {sound_velocity}")
    expected_length = 12 + 72 + count * 4
    if length != expected_length:
        raise ValueError(f"RAW0 length mismatch: {length} != {expected_length}")
    return {
        "channel": channel,
        "frequency_hz": frequency,
        "sample_interval_seconds": sample_interval,
        "sound_velocity_m_s": sound_velocity,
        "sample_offset": sample_offset,
        "sample_count": count,
    }


def signed_values(payload: bytes) -> tuple[int, ...]:
    return struct.unpack(f"{len(payload)}b", payload)


def profile_stats(payload: bytes) -> dict[str, object]:
    values = signed_values(payload)
    distinct = len(set(values))
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if len(values) != RANGE_BIN_COUNT or distinct < 250 or transitions < 3_000:
        raise ValueError(
            f"degenerate angle profile: values={len(values)} distinct={distinct} transitions={transitions}"
        )
    return {
        "minimum": min(values),
        "maximum": max(values),
        "distinct_values": distinct,
        "zero_values": values.count(0),
        "flattened_transitions": transitions,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
    }


def scan(download_dir: Path) -> tuple[list[dict[str, object]], dict[str, int]]:
    source = validate_source(download_dir)
    raw = source.read_bytes()
    position = 0
    type_counts: Counter[str] = Counter()
    reports: list[dict[str, object]] = []
    hashes = {name: set() for name, _series, _offset in COMPONENTS}
    con_payload = None
    while position < len(raw):
        if position + 20 > len(raw):
            raise SystemExit(f"truncated datagram header at byte {position}")
        length = struct.unpack_from("<i", raw, position)[0]
        end = position + 4 + length
        next_position = end + 4
        if length < 12 or next_position > len(raw):
            raise SystemExit(f"invalid datagram length {length} at byte {position}")
        kind = raw[position + 4 : position + 8].decode("ascii", "replace")
        if kind not in {"CON0", "NME0", "RAW0"}:
            raise SystemExit(f"unexpected datagram type {kind!r} at byte {position}")
        if struct.unpack_from("<i", raw, end)[0] != length:
            raise SystemExit(f"datagram trailer mismatch at byte {position}")
        type_counts[kind] += 1
        low, high = struct.unpack_from("<II", raw, position + 8)
        timestamp = (high << 32) | low
        if kind == "CON0":
            if con_payload is not None:
                raise SystemExit("multiple CON0 datagrams")
            con_payload = raw[position + 16 : end]
        elif kind == "RAW0":
            try:
                header = raw0_header(raw, position, length)
            except ValueError as error:
                raise SystemExit(f"RAW0 at byte {position}: {error}") from error
            angle_start = position + 16 + 72 + RANGE_BIN_COUNT * 2
            interleaved = raw[angle_start : angle_start + RANGE_BIN_COUNT * 2]
            if len(interleaved) != RANGE_BIN_COUNT * 2:
                raise SystemExit(f"truncated RAW0 angle array at byte {position}")
            components: dict[str, dict[str, object]] = {}
            for name, _series, byte_offset in COMPONENTS:
                payload = interleaved[byte_offset::2]
                try:
                    stats = profile_stats(payload)
                except ValueError as error:
                    raise SystemExit(f"RAW0 {name} at byte {position}: {error}") from error
                digest = str(stats["sha256"])
                if digest in hashes[name]:
                    raise SystemExit(f"duplicate RAW0 {name} profile at byte {position}")
                hashes[name].add(digest)
                components[name] = {"payload": payload, **stats}
            reports.append(
                {
                    "source_datagram_offset": position,
                    "timestamp_filetime": timestamp,
                    **header,
                    "components": components,
                }
            )
        position = next_position
    if position != len(raw):
        raise SystemExit("datagram scan did not end at source EOF")
    expected_types = {"CON0": 1, "NME0": 30_407, "RAW0": PROFILE_COUNT}
    if dict(type_counts) != expected_types:
        raise SystemExit(f"datagram type counts changed: {dict(type_counts)} != {expected_types}")
    if con_payload is None or not con_payload.startswith(b"PolarFront0522\x00"):
        raise SystemExit("CON0 survey identity changed")
    for marker in (b"ER60\x00", b"GPT  18 kHz", b"GPT  38 kHz", b"GPT 120 kHz"):
        if marker not in con_payload:
            raise SystemExit(f"CON0 transducer marker missing: {marker!r}")
    if len(reports) != PROFILE_COUNT:
        raise SystemExit(f"RAW0 count changed: {len(reports)}")
    previous_timestamp = -1
    for ping in range(PING_COUNT):
        group = reports[ping * 3 : ping * 3 + 3]
        timestamp = int(group[0]["timestamp_filetime"])
        signature = tuple((int(row["channel"]), float(row["frequency_hz"])) for row in group)
        if signature != CHANNEL_FREQUENCIES or any(int(row["timestamp_filetime"]) != timestamp for row in group):
            raise SystemExit(f"invalid synchronized channel group at ping {ping}")
        if timestamp <= previous_timestamp:
            raise SystemExit(f"non-increasing RAW0 ping timestamp at ping {ping}")
        previous_timestamp = timestamp
        for row in group:
            row["ping_index"] = ping
    return reports, expected_types


def aggregate(reports: list[dict[str, object]], type_counts: dict[str, int]) -> dict[str, object]:
    component_summary: dict[str, dict[str, object]] = {}
    for name, series_id, _offset in COMPONENTS:
        stats = [row["components"][name] for row in reports]  # type: ignore[index]
        ratios = [float(item["zlib_ratio"]) for item in stats]
        component_summary[name] = {
            "series_id": series_id,
            "sample_count": len(stats),
            "value_count": len(stats) * RANGE_BIN_COUNT,
            "total_size_bytes": len(stats) * RANGE_BIN_COUNT,
            "unique_payloads": len({str(item["sha256"]) for item in stats}),
            "global_minimum": min(int(item["minimum"]) for item in stats),
            "global_maximum": max(int(item["maximum"]) for item in stats),
            "minimum_distinct_values": min(int(item["distinct_values"]) for item in stats),
            "minimum_transitions": min(int(item["flattened_transitions"]) for item in stats),
            "zero_values": sum(int(item["zero_values"]) for item in stats),
            "minimum_zlib_ratio": min(ratios),
            "median_zlib_ratio": statistics.median(ratios),
            "maximum_zlib_ratio": max(ratios),
        }
    result = {
        "dataset_id": DATASET_ID,
        "sample_count": TOTAL_SAMPLE_COUNT,
        "profile_count_per_component": PROFILE_COUNT,
        "ping_count": PING_COUNT,
        "channel_count": len(CHANNEL_FREQUENCIES),
        "value_count": TOTAL_VALUE_COUNT,
        "total_size_bytes": TOTAL_SIZE_BYTES,
        "first_timestamp_filetime": int(reports[0]["timestamp_filetime"]),
        "last_timestamp_filetime": int(reports[-1]["timestamp_filetime"]),
        "source_datagram_counts": type_counts,
        "components": component_summary,
    }
    expected = {
        "alongship": {"unique_payloads": PROFILE_COUNT, "global_minimum": -128, "global_maximum": 127,
                      "minimum_distinct_values": 255, "minimum_transitions": 3_119, "zero_values": 54_798},
        "athwartship": {"unique_payloads": PROFILE_COUNT, "global_minimum": -128, "global_maximum": 127,
                        "minimum_distinct_values": 255, "minimum_transitions": 3_118, "zero_values": 49_554},
    }
    for name, fields in expected.items():
        for key, value in fields.items():
            if component_summary[name][key] != value:
                raise SystemExit(
                    f"aggregate source statistic changed for {name}.{key}: "
                    f"{component_summary[name][key]} != {value}"
                )
    if result["first_timestamp_filetime"] != 132_978_456_716_688_227:
        raise SystemExit("first RAW0 timestamp changed")
    if result["last_timestamp_filetime"] != 132_978_473_927_562_633:
        raise SystemExit("last RAW0 timestamp changed")
    return result


def public_report(report: dict[str, object]) -> dict[str, object]:
    result = {key: value for key, value in report.items() if key != "components"}
    result["components"] = {
        name: {key: value for key, value in component.items() if key != "payload"}
        for name, component in report["components"].items()  # type: ignore[union-attr]
    }
    return result


def inspect(args: argparse.Namespace) -> None:
    reports, type_counts = scan(args.download_dir)
    print(json.dumps(aggregate(reports, type_counts), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    reports, type_counts = scan(args.download_dir)
    summary = aggregate(reports, type_counts)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    for _name, series_id, _offset in COMPONENTS:
        (args.samples_dir / series_id).mkdir(parents=True)
    rows = []
    for report in reports:
        ping = int(report["ping_index"])
        channel = int(report["channel"])
        frequency = int(float(report["frequency_hz"]))
        for name, series_id, _offset in COMPONENTS:
            component = report["components"][name]  # type: ignore[index]
            payload = component["payload"]
            output = args.samples_dir / series_id / f"ping_{ping:04d}_ch{channel}_{frequency}hz_{name}_i8.bin"
            output.write_bytes(payload)
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": series_id,
                    "role": "primary",
                    "sample_path": output.relative_to(args.data_root).as_posix(),
                    "source_sample": f"downloads/{DATASET_ID}/{SOURCE_NAME}",
                    "source_datagram_offset": report["source_datagram_offset"],
                    "ping_index": ping,
                    "channel": channel,
                    "frequency_hz": report["frequency_hz"],
                    "timestamp_filetime": report["timestamp_filetime"],
                    "sample_interval_seconds": report["sample_interval_seconds"],
                    "sound_velocity_m_s": report["sound_velocity_m_s"],
                    "sample_offset": report["sample_offset"],
                    "angle_component": name,
                    "numeric_kind": "int",
                    "bit_width": 8,
                    "endianness": "little",
                    "element_size_bytes": 1,
                    "value_count": RANGE_BIN_COUNT,
                    "sample_size_bytes": RANGE_BIN_COUNT,
                    "sample_format": f"raw homogeneous signed-int8 EK60 {name} angle-code vector",
                    "sample_geometry": "ek60_ping_channel_range_profile",
                    "sample_rank": 1,
                    "sample_shape": [RANGE_BIN_COUNT],
                    "sample_axes": ["range_bin"],
                    "natural_record_kind": f"complete_ping_channel_{name}_angle_profile",
                    "minimum": component["minimum"],
                    "maximum": component["maximum"],
                    "distinct_values": component["distinct_values"],
                    "sha256": component["sha256"],
                }
            )
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    summary["source_name"] = SOURCE_NAME
    summary["source_md5"] = SOURCE_MD5
    summary["channel_frequencies"] = [list(item) for item in CHANNEL_FREQUENCIES]
    summary["profiles"] = [public_report(report) for report in reports]
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "profiles"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    reports, type_counts = scan(args.download_dir)
    expected_summary = aggregate(reports, type_counts)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != TOTAL_SAMPLE_COUNT:
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs: set[Path] = set()
    row_index = 0
    for report in reports:
        ping = int(report["ping_index"])
        channel = int(report["channel"])
        for name, series_id, _offset in COMPONENTS:
            row = rows[row_index]
            row_index += 1
            component = report["components"][name]  # type: ignore[index]
            if row.get("dataset_id") != DATASET_ID or row.get("series_id") != series_id or row.get("role") != "primary":
                raise SystemExit(f"unexpected dataset/series/role at ping {ping} channel {channel} component {name}")
            if int(row.get("ping_index", -1)) != ping or int(row.get("channel", 0)) != channel:
                raise SystemExit(f"profile ordering mismatch at ping {ping} channel {channel} component {name}")
            if row.get("angle_component") != name or row.get("sample_shape") != [RANGE_BIN_COUNT]:
                raise SystemExit(f"component or shape mismatch at ping {ping} channel {channel} component {name}")
            if row.get("numeric_kind") != "int" or int(row.get("bit_width", 0)) != 8 or row.get("endianness") != "little":
                raise SystemExit(f"numeric representation mismatch at ping {ping} channel {channel} component {name}")
            output = args.data_root / str(row["sample_path"])
            expected_outputs.add(output.resolve())
            if not output.is_file() or output.read_bytes() != component["payload"]:
                raise SystemExit(f"output differs from RAW0 at ping {ping} channel {channel} component {name}")
            if row.get("sha256") != component["sha256"] or int(row.get("timestamp_filetime")) != report["timestamp_filetime"]:
                raise SystemExit(f"indexed hash or timestamp mismatch at ping {ping} channel {channel} component {name}")
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stored = json.loads(args.stats.read_text(encoding="utf-8"))
    for key, value in expected_summary.items():
        if stored.get(key) != value:
            raise SystemExit(f"ingest statistic mismatch for {key}: {stored.get(key)} != {value}")
    if stored.get("source_md5") != SOURCE_MD5:
        raise SystemExit("stored source identity differs")
    expected_profiles = [public_report(report) for report in reports]
    if stored.get("profiles") != expected_profiles:
        raise SystemExit("stored per-profile reports differ")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": TOTAL_SAMPLE_COUNT,
        "verified_values": TOTAL_VALUE_COUNT,
        "verified_bytes": TOTAL_SIZE_BYTES,
        "source_md5": SOURCE_MD5,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
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
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
