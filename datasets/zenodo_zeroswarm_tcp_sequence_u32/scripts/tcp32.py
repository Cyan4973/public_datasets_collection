#!/usr/bin/env python3
"""Preflight, build, and verify native TCP uint32 transport trajectories."""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
from typing import Callable, Iterator


DATASET_ID = "zenodo_zeroswarm_tcp_sequence_u32"
SERIES_IDS = {
    "sequence": "zeroswarm_tcp_sequence_u32",
    "acknowledgment": "zeroswarm_tcp_acknowledgment_u32",
}
CAPTURE_ORDER = ("v2", "v2b")
FIELD_ORDER = ("sequence", "acknowledgment")
DIRECTION_ORDER = ("request", "response")
EXPECTED_SELECTION_COLUMNS = (
    "capture_id", "filename", "size_bytes", "md5", "source_sha256", "url",
)
EXPECTED_PROFILE_COLUMNS = (
    "capture_id", "field", "direction", "value_count", "distinct_values",
    "minimum", "maximum", "transitions", "decreases", "little_endian_sha256",
)
EXPECTED_RECORD = (
    5_364,
    "6dded3622c3f2f7fcaa3c74e89c3a51c43af94eb63546a6da510b8a65e193ffb",
)
EXPECTED_VALUES_PER_SERIES = 3_035_941
EXPECTED_BYTES_PER_SERIES = EXPECTED_VALUES_PER_SERIES * 4
EXPECTED_TOTAL_VALUES = EXPECTED_VALUES_PER_SERIES * 2
EXPECTED_TOTAL_BYTES = EXPECTED_BYTES_PER_SERIES * 2
EXPECTED_AGGREGATE_SHA256 = {
    "sequence": "6a8f3a585ae1e8dbd3ba29c28fb684629f1c0001cfe7fbdfcaebe242bd71168c",
    "acknowledgment": "ced3c186a348d73f71a346fceeed1e05dd77ca3ff199c54bdfc0816a8a937d0f",
}
PayloadConsumer = Callable[
    [dict[str, str], str, str, bytes, dict[str, object]], None
]


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_identity(
    path: Path, size: int, digest: str, label: str, algorithm: str = "sha256"
) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    if path.stat().st_size != size or file_hash(path, algorithm) != digest:
        raise SystemExit(f"{label} identity mismatch")


def load_selection(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != EXPECTED_SELECTION_COLUMNS:
            raise SystemExit("selection.tsv schema changed")
        rows = list(reader)
    if tuple(row["capture_id"] for row in rows) != CAPTURE_ORDER:
        raise SystemExit("capture selection count or order changed")
    return rows


def load_profiles(path: Path) -> dict[tuple[str, str, str], dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != EXPECTED_PROFILE_COLUMNS:
            raise SystemExit("profiles.tsv schema changed")
        raw = list(reader)
    expected_keys = [
        (capture, field, direction)
        for capture in CAPTURE_ORDER
        for field in FIELD_ORDER
        for direction in DIRECTION_ORDER
    ]
    if [(row["capture_id"], row["field"], row["direction"]) for row in raw] != expected_keys:
        raise SystemExit("profile count or order changed")
    profiles = {}
    for row in raw:
        key = (row["capture_id"], row["field"], row["direction"])
        profiles[key] = {
            "value_count": int(row["value_count"]),
            "distinct_values": int(row["distinct_values"]),
            "minimum": int(row["minimum"]),
            "maximum": int(row["maximum"]),
            "transitions": int(row["transitions"]),
            "decreases": int(row["decreases"]),
            "sha256": row["little_endian_sha256"],
        }
    return profiles


def validate_record(path: Path, selection: list[dict[str, str]]) -> dict[str, object]:
    validate_identity(path, *EXPECTED_RECORD, "Zenodo record metadata")
    record = json.loads(path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    if (
        int(record.get("id", 0)) != 15_082_260
        or metadata.get("title") != "Modbus Normal and Malicious Network Traffic"
        or metadata.get("doi") != "10.5281/zenodo.15082260"
        or str(metadata.get("license", {}).get("id", "")).lower() != "cc-by-4.0"
    ):
        raise SystemExit("Zenodo record identity or license changed")
    files = {item.get("key"): item for item in record.get("files", [])}
    for row in selection:
        item = files.get(row["filename"])
        if (
            not isinstance(item, dict)
            or int(item.get("size", 0)) != int(row["size_bytes"])
            or item.get("checksum") != f"md5:{row['md5']}"
            or item.get("links", {}).get("self") != row["url"]
        ):
            raise SystemExit(f"Zenodo file metadata changed: {row['filename']}")
    return {
        "record_id": 15_082_260,
        "doi": "10.5281/zenodo.15082260",
        "title": metadata["title"],
        "license": "CC BY 4.0",
        "size_bytes": path.stat().st_size,
        "sha256": file_hash(path),
    }


def pcap_packets(path: Path) -> tuple[int, Iterator[bytes]]:
    handle = path.open("rb")
    header = handle.read(24)
    if len(header) != 24:
        handle.close()
        raise ValueError("truncated PCAP global header")
    endian_by_magic = {
        b"\xd4\xc3\xb2\xa1": "<",
        b"\xa1\xb2\xc3\xd4": ">",
        b"\x4d\x3c\xb2\xa1": "<",
        b"\xa1\xb2\x3c\x4d": ">",
    }
    if header[:4] not in endian_by_magic:
        handle.close()
        raise ValueError("unsupported PCAP magic")
    endian = endian_by_magic[header[:4]]
    _, major, minor, _, _, snaplen, linktype = struct.unpack(
        endian + "IHHIIII", header
    )
    if (major, minor) != (2, 4) or snaplen <= 0:
        handle.close()
        raise ValueError("invalid PCAP version or snaplen")

    def iterator() -> Iterator[bytes]:
        packet_index = 0
        try:
            while True:
                record = handle.read(16)
                if not record:
                    break
                if len(record) != 16:
                    raise ValueError(f"truncated packet header at {packet_index}")
                _, _, captured, original = struct.unpack(endian + "IIII", record)
                if captured > snaplen or captured > original:
                    raise ValueError(f"invalid packet lengths at {packet_index}")
                frame = handle.read(captured)
                if len(frame) != captured:
                    raise ValueError(f"truncated packet payload at {packet_index}")
                yield frame
                packet_index += 1
        finally:
            handle.close()

    return linktype, iterator()


def tcp_counters(frame: bytes) -> tuple[str, int, int] | None:
    if len(frame) < 14:
        return None
    ethernet_offset = 14
    ethertype = struct.unpack_from(">H", frame, 12)[0]
    while ethertype in {0x8100, 0x88A8, 0x9100}:
        if len(frame) < ethernet_offset + 4:
            return None
        ethertype = struct.unpack_from(">H", frame, ethernet_offset + 2)[0]
        ethernet_offset += 4
    if ethertype != 0x0800 or len(frame) < ethernet_offset + 20:
        return None
    version_ihl = frame[ethernet_offset]
    ihl = (version_ihl & 0x0F) * 4
    if version_ihl >> 4 != 4 or ihl < 20:
        return None
    if len(frame) < ethernet_offset + ihl + 20 or frame[ethernet_offset + 9] != 6:
        return None
    flags_fragment = struct.unpack_from(">H", frame, ethernet_offset + 6)[0]
    if flags_fragment & 0x3FFF:
        return None
    total_length = struct.unpack_from(">H", frame, ethernet_offset + 2)[0]
    ip_end = min(len(frame), ethernet_offset + total_length)
    tcp_offset = ethernet_offset + ihl
    if total_length < ihl + 20 or ip_end < tcp_offset + 20:
        return None
    source_port, destination_port = struct.unpack_from(">HH", frame, tcp_offset)
    if source_port != 502 and destination_port != 502:
        return None
    data_offset = (frame[tcp_offset + 12] >> 4) * 4
    if data_offset < 20 or ip_end < tcp_offset + data_offset:
        return None
    sequence, acknowledgment = struct.unpack_from(">II", frame, tcp_offset + 4)
    direction = "response" if source_port == 502 else "request"
    return direction, sequence, acknowledgment


def uint32_le_payload(values: array) -> bytes:
    output = array("I", values)
    if output.itemsize != 4:
        raise ValueError("host unsigned-int width is not 32 bits")
    if sys.byteorder == "big":
        output.byteswap()
    return output.tobytes()


def payload_profile(values: array) -> tuple[dict[str, object], bytes]:
    if not values:
        raise ValueError("empty TCP counter stream")
    payload = uint32_le_payload(values)
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    decreases = sum(right < left for left, right in zip(values, values[1:]))
    step_counts = Counter(
        (right - left) & 0xFFFFFFFF
        for left, right in zip(values, values[1:])
        if right != left
    )
    return {
        "value_count": len(values),
        "sample_size_bytes": len(payload),
        "distinct_values": len(set(values)),
        "minimum": min(values),
        "maximum": max(values),
        "transitions": transitions,
        "plateaus": len(values) - 1 - transitions,
        "decreases": decreases,
        "top_nonzero_steps": [
            {"step": step, "count": count}
            for step, count in step_counts.most_common(10)
        ],
        "sha256": hashlib.sha256(payload).hexdigest(),
    }, payload


def inspect_capture(
    path: Path,
    row: dict[str, str],
    expected_profiles: dict[tuple[str, str, str], dict[str, object]],
    consumer: Callable[[str, str, bytes, dict[str, object]], None] | None = None,
) -> dict[str, object]:
    validate_identity(
        path, int(row["size_bytes"]), row["source_sha256"], row["capture_id"]
    )
    if file_hash(path, "md5") != row["md5"]:
        raise SystemExit(f"{row['capture_id']}: source MD5 mismatch")
    linktype, packets = pcap_packets(path)
    if linktype != 1:
        raise SystemExit(f"{row['capture_id']}: expected Ethernet linktype 1")
    streams = {
        (field, direction): array("I")
        for field in FIELD_ORDER
        for direction in DIRECTION_ORDER
    }
    packet_count = 0
    qualifying_packets = 0
    for frame in packets:
        packet_count += 1
        counters = tcp_counters(frame)
        if counters is None:
            continue
        qualifying_packets += 1
        direction, sequence, acknowledgment = counters
        streams[("sequence", direction)].append(sequence)
        streams[("acknowledgment", direction)].append(acknowledgment)
    profiles = {}
    for field in FIELD_ORDER:
        for direction in DIRECTION_ORDER:
            key = (field, direction)
            try:
                metrics, payload = payload_profile(streams[key])
            except ValueError as error:
                raise SystemExit(f"{row['capture_id']} {field} {direction}: {error}") from error
            expected = expected_profiles[(row["capture_id"], field, direction)]
            for metric, value in expected.items():
                if metrics[metric] != value:
                    raise SystemExit(
                        f"{row['capture_id']} {field} {direction}: {metric} changed"
                    )
            profiles[f"{field}_{direction}"] = metrics
            if consumer is not None:
                consumer(field, direction, payload, metrics)
    if qualifying_packets != (
        int(profiles["sequence_request"]["value_count"])
        + int(profiles["sequence_response"]["value_count"])
    ):
        raise SystemExit(f"{row['capture_id']}: qualifying packet count mismatch")
    return {
        "capture_id": row["capture_id"],
        "filename": row["filename"],
        "size_bytes": int(row["size_bytes"]),
        "md5": row["md5"],
        "sha256": row["source_sha256"],
        "pcap_linktype": linktype,
        "packet_count": packet_count,
        "qualifying_modbus_tcp_packet_count": qualifying_packets,
        "stream_profiles": profiles,
    }


def scan_source(
    selection_path: Path,
    profiles_path: Path,
    record_path: Path,
    download_dir: Path,
    consumer: PayloadConsumer | None = None,
) -> dict[str, object]:
    selection = load_selection(selection_path)
    expected_profiles = load_profiles(profiles_path)
    record = validate_record(record_path, selection)
    aggregates = {field: hashlib.sha256() for field in FIELD_ORDER}
    output_hashes = {field: set() for field in FIELD_ORDER}
    capture_profiles = []
    for row in selection:
        def observe(
            field: str, direction: str, payload: bytes, metrics: dict[str, object]
        ) -> None:
            digest = str(metrics["sha256"])
            if digest in output_hashes[field]:
                raise SystemExit(
                    f"duplicate {field} payload: {row['capture_id']} {direction}"
                )
            output_hashes[field].add(digest)
            aggregates[field].update(payload)
            if consumer is not None:
                consumer(row, field, direction, payload, metrics)

        capture_profiles.append(
            inspect_capture(
                download_dir / row["filename"], row, expected_profiles, observe
            )
        )
    series_profiles = {}
    for field in FIELD_ORDER:
        profile = {
            "series_id": SERIES_IDS[field],
            "sample_count": len(CAPTURE_ORDER) * len(DIRECTION_ORDER),
            "value_count": EXPECTED_VALUES_PER_SERIES,
            "total_size_bytes": EXPECTED_BYTES_PER_SERIES,
            "aggregate_capture_direction_order_sha256": aggregates[field].hexdigest(),
        }
        pinned = EXPECTED_AGGREGATE_SHA256.get(field)
        if pinned and profile["aggregate_capture_direction_order_sha256"] != pinned:
            raise SystemExit(f"aggregate {field} payload hash changed")
        series_profiles[field] = profile
    return {
        "dataset_id": DATASET_ID,
        "record": record,
        "capture_count": len(capture_profiles),
        "sample_count": len(CAPTURE_ORDER) * len(DIRECTION_ORDER) * len(FIELD_ORDER),
        "primary_value_count": EXPECTED_TOTAL_VALUES,
        "primary_size_bytes": EXPECTED_TOTAL_BYTES,
        "series_profiles": series_profiles,
        "captures": capture_profiles,
    }


def index_entry(
    row: dict[str, str],
    field: str,
    direction: str,
    metrics: dict[str, object],
    output: Path,
    source: Path,
    data_root: Path,
) -> dict[str, object]:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_IDS[field],
        "role": "primary",
        "sample_path": output.relative_to(data_root).as_posix(),
        "source_sample": source.relative_to(data_root).as_posix(),
        "source_field": f"TCP {field} number for {direction} port-502 packets",
        "capture_id": row["capture_id"],
        "direction": direction,
        "numeric_kind": "uint",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "value_count": metrics["value_count"],
        "sample_size_bytes": metrics["sample_size_bytes"],
        "sample_format": f"raw homogeneous uint32 TCP {field}-number trajectory",
        "sample_geometry": "tcp_sequence_space_packet_timeline_1d",
        "sample_rank": 1,
        "sample_shape": [metrics["value_count"]],
        "sample_axes": [f"{direction}_packet_capture_order"],
        "natural_record_kind": "pcap_tcp_counter_field_direction",
        "distinct_values": metrics["distinct_values"],
        "minimum": metrics["minimum"],
        "maximum": metrics["maximum"],
        "transitions": metrics["transitions"],
        "plateaus": metrics["plateaus"],
        "decreases": metrics["decreases"],
        "sha256": metrics["sha256"],
    }


def preflight(args: argparse.Namespace) -> None:
    result = scan_source(
        args.selection, args.profiles, args.record, args.download_dir
    )
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "captures"}, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    args.samples_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, object]] = []

    def emit(
        row: dict[str, str], field: str, direction: str,
        payload: bytes, metrics: dict[str, object],
    ) -> None:
        series_dir = args.samples_dir / SERIES_IDS[field]
        series_dir.mkdir(exist_ok=True)
        output = series_dir / (
            f"zeroswarm_{row['capture_id']}_{direction}_{field}_u32_"
            f"n{metrics['value_count']}.bin"
        )
        output.write_bytes(payload)
        source = args.download_dir / row["filename"]
        index_rows.append(
            index_entry(row, field, direction, metrics, output, source, args.data_root)
        )

    result = scan_source(
        args.selection, args.profiles, args.record, args.download_dir, emit
    )
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "captures"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or statistics; run build first")
    indexed = [
        json.loads(line)
        for line in args.index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(
        row: dict[str, str], field: str, direction: str,
        payload: bytes, metrics: dict[str, object],
    ) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than streams")
        output = args.samples_dir / SERIES_IDS[field] / (
            f"zeroswarm_{row['capture_id']}_{direction}_{field}_u32_"
            f"n{metrics['value_count']}.bin"
        )
        source = args.download_dir / row["filename"]
        expected = index_entry(
            row, field, direction, metrics, output, source, args.data_root
        )
        if indexed[cursor] != expected:
            raise SystemExit(f"index mismatch at row {cursor + 1}")
        cursor += 1
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh PCAP decode: {output}")
        expected_outputs.add(output.resolve())

    result = scan_source(
        args.selection, args.profiles, args.record, args.download_dir, compare
    )
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if json.loads(args.stats.read_text(encoding="utf-8")) != result:
        raise SystemExit("ingest statistics differ from fresh source scan")
    print(
        f"verified_samples={cursor} values={result['primary_value_count']} "
        f"bytes={result['primary_size_bytes']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "build", "verify"))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--samples-dir", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if args.command == "preflight":
        if args.profile is None:
            parser.error("preflight requires --profile")
        preflight(args)
    elif args.command == "build":
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("build requires --samples-dir, --index, --stats, and --data-root")
        build(args)
    else:
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("verify requires --samples-dir, --index, --stats, and --data-root")
        verify(args)


if __name__ == "__main__":
    main()
