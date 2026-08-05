#!/usr/bin/env python3
"""Decode native int16 power vectors from one pinned Simrad EK60 recording."""
from __future__ import annotations

from array import array
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys
import zlib


DATASET_ID = "zenodo_polarfront_ek60_power_i16"
SERIES_ID = "ek60_ping_channel_power_i16"
RECORD_ID = 7473204
RECORD_TITLE = "Split-beam echosounder data from keel-mounted EK60 during PolarFront 2022-05 cruise"
SOURCE_NAME = "PolarFront0522-D20220524-T060111.raw"
SOURCE_SIZE = 45_896_704
SOURCE_MD5 = "944f3af1aea3a51cfa7ef7912dde10ba"
PING_COUNT = 1_147
CHANNEL_FREQUENCIES = ((1, 18_000.0), (2, 38_000.0), (3, 120_000.0))
SAMPLE_COUNT = 3_188
VECTOR_BYTES = SAMPLE_COUNT * 2
VECTOR_COUNT = PING_COUNT * len(CHANNEL_FREQUENCIES)
TOTAL_VALUES = VECTOR_COUNT * SAMPLE_COUNT
TOTAL_BYTES = VECTOR_COUNT * VECTOR_BYTES


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
    if sample_offset != 0 or count != SAMPLE_COUNT:
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


def power_stats(payload: bytes) -> dict[str, object]:
    values = array("h")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    distinct = len(set(values))
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if len(values) != SAMPLE_COUNT or distinct < 1_400 or transitions < 3_000:
        raise ValueError(
            f"degenerate power vector: values={len(values)} distinct={distinct} transitions={transitions}"
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


def scan(download_dir: Path) -> tuple[list[dict[str, object]], list[bytes], dict[str, int]]:
    source = validate_source(download_dir)
    raw = source.read_bytes()
    position = 0
    type_counts: Counter[str] = Counter()
    reports = []
    payloads = []
    hashes: set[str] = set()
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
            power_start = position + 16 + 72
            payload = raw[power_start : power_start + VECTOR_BYTES]
            try:
                stats = power_stats(payload)
            except ValueError as error:
                raise SystemExit(f"RAW0 at byte {position}: {error}") from error
            digest = str(stats["sha256"])
            if digest in hashes:
                raise SystemExit(f"duplicate RAW0 power payload at byte {position}")
            hashes.add(digest)
            reports.append(
                {
                    "source_datagram_offset": position,
                    "timestamp_filetime": timestamp,
                    **header,
                    **stats,
                }
            )
            payloads.append(payload)
        position = next_position
    if position != len(raw):
        raise SystemExit("datagram scan did not end at source EOF")
    expected_types = {"CON0": 1, "NME0": 30_407, "RAW0": VECTOR_COUNT}
    if dict(type_counts) != expected_types:
        raise SystemExit(f"datagram type counts changed: {dict(type_counts)} != {expected_types}")
    if con_payload is None or not con_payload.startswith(b"PolarFront0522\x00"):
        raise SystemExit("CON0 survey identity changed")
    for marker in (b"ER60\x00", b"GPT  18 kHz", b"GPT  38 kHz", b"GPT 120 kHz"):
        if marker not in con_payload:
            raise SystemExit(f"CON0 transducer marker missing: {marker!r}")
    if len(reports) != VECTOR_COUNT:
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
    return reports, payloads, expected_types


def aggregate(reports: list[dict[str, object]], type_counts: dict[str, int]) -> dict[str, object]:
    ratios = [float(row["zlib_ratio"]) for row in reports]
    result = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(reports),
        "ping_count": PING_COUNT,
        "channel_count": len(CHANNEL_FREQUENCIES),
        "value_count": len(reports) * SAMPLE_COUNT,
        "total_size_bytes": len(reports) * VECTOR_BYTES,
        "unique_payloads": len({str(row["sha256"]) for row in reports}),
        "global_minimum": min(int(row["minimum"]) for row in reports),
        "global_maximum": max(int(row["maximum"]) for row in reports),
        "minimum_distinct_values": min(int(row["distinct_values"]) for row in reports),
        "zero_values": sum(int(row["zero_values"]) for row in reports),
        "first_timestamp_filetime": int(reports[0]["timestamp_filetime"]),
        "last_timestamp_filetime": int(reports[-1]["timestamp_filetime"]),
        "minimum_zlib_ratio": min(ratios),
        "median_zlib_ratio": statistics.median(ratios),
        "maximum_zlib_ratio": max(ratios),
        "source_datagram_counts": type_counts,
    }
    expected = {
        "sample_count": VECTOR_COUNT,
        "value_count": TOTAL_VALUES,
        "total_size_bytes": TOTAL_BYTES,
        "unique_payloads": VECTOR_COUNT,
        "global_minimum": -18_746,
        "global_maximum": 2_404,
        "minimum_distinct_values": 1_431,
        "zero_values": 0,
        "first_timestamp_filetime": 132_978_456_716_688_227,
        "last_timestamp_filetime": 132_978_473_927_562_633,
    }
    for key, value in expected.items():
        if result[key] != value:
            raise SystemExit(f"aggregate source statistic changed for {key}: {result[key]} != {value}")
    return result


def inspect(args: argparse.Namespace) -> None:
    reports, _payloads, type_counts = scan(args.download_dir)
    print(json.dumps(aggregate(reports, type_counts), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    reports, payloads, type_counts = scan(args.download_dir)
    summary = aggregate(reports, type_counts)
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for report, payload in zip(reports, payloads, strict=True):
        ping = int(report["ping_index"])
        channel = int(report["channel"])
        frequency = int(float(report["frequency_hz"]))
        output = series_dir / f"ping_{ping:04d}_ch{channel}_{frequency}hz_i16le.bin"
        output.write_bytes(payload)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
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
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "value_count": SAMPLE_COUNT,
                "sample_size_bytes": VECTOR_BYTES,
                "sample_format": "raw homogeneous signed-int16 EK60 acoustic power vector",
                "sample_geometry": "ek60_ping_channel_range_profile",
                "sample_rank": 1,
                "sample_shape": [SAMPLE_COUNT],
                "sample_axes": ["range_bin"],
                "natural_record_kind": "complete_ping_channel_power_profile",
                "minimum": report["minimum"],
                "maximum": report["maximum"],
                "distinct_values": report["distinct_values"],
                "sha256": report["sha256"],
            }
        )
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    summary["source_name"] = SOURCE_NAME
    summary["source_md5"] = SOURCE_MD5
    summary["channel_frequencies"] = [list(item) for item in CHANNEL_FREQUENCIES]
    summary["profiles"] = reports
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "profiles"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    reports, payloads, type_counts = scan(args.download_dir)
    expected_summary = aggregate(reports, type_counts)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != VECTOR_COUNT:
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs: set[Path] = set()
    for row, report, payload in zip(rows, reports, payloads, strict=True):
        ping = int(report["ping_index"])
        channel = int(report["channel"])
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit(f"unexpected dataset/series/role at ping {ping} channel {channel}")
        if int(row.get("ping_index", -1)) != ping or int(row.get("channel", 0)) != channel or row.get("sample_shape") != [SAMPLE_COUNT]:
            raise SystemExit(f"profile ordering or shape mismatch at ping {ping} channel {channel}")
        if row.get("numeric_kind") != "int" or int(row.get("bit_width", 0)) != 16 or row.get("endianness") != "little":
            raise SystemExit(f"numeric representation mismatch at ping {ping} channel {channel}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output is not byte-identical to RAW0 power at ping {ping} channel {channel}")
        if row.get("sha256") != report["sha256"] or int(row.get("timestamp_filetime")) != report["timestamp_filetime"]:
            raise SystemExit(f"indexed hash or timestamp mismatch at ping {ping} channel {channel}")
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stored = json.loads(args.stats.read_text(encoding="utf-8"))
    for key, value in expected_summary.items():
        if stored.get(key) != value:
            raise SystemExit(f"ingest statistic mismatch for {key}: {stored.get(key)} != {value}")
    if stored.get("source_md5") != SOURCE_MD5 or stored.get("profiles") != reports:
        raise SystemExit("stored source identity or per-profile reports differ")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": VECTOR_COUNT,
        "verified_values": TOTAL_VALUES,
        "verified_bytes": TOTAL_BYTES,
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
