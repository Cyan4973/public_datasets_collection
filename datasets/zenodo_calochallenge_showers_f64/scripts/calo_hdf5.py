#!/usr/bin/env python3
"""Range-plan and decode the pinned CaloChallenge Dataset 2 HDF5 matrix."""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import math
import mmap
from pathlib import Path
import shutil
import struct
import sys
import zlib


DATASET_ID = "zenodo_calochallenge_showers_f64"
SERIES_ID = "calochallenge_electron_shower_energy_f64"
RECORD_ID = 6_366_271
DOI = "10.5281/zenodo.6366271"
SOURCE_NAME = "dataset_2_1.hdf5"
SOURCE_SIZE = 1_356_475_617
SOURCE_MD5 = "e590333e9a2da51b258288d74bd8357a"
PREFIX_SIZE = 4_194_304
SOURCE_SHAPE = (100_000, 6_480)
CHUNK_SHAPE = (391, 51)
EVENT_VALUES = 6_480
EVENT_BYTES = EVENT_VALUES * 8
DEFAULT_EVENT_COUNT = 3_910
NODE_FETCH_BYTES = 4_096
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
H5T_IEEE_F64LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
EXPECTED_VALUE_COUNT = 25_336_800
EXPECTED_OUTPUT_BYTES = 202_694_400
EXPECTED_ZERO_COUNT = 19_167_727
EXPECTED_MINIMUM = 0.0
EXPECTED_MAXIMUM = 4248.93169359166
EXPECTED_AGGREGATE_SHA256 = "a2a8b302b1a6d2c08df8da9e90a9f0bb034c5d0a045917f5162c61c0532184d0"


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def u16(raw: bytes | mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<H", raw, offset)[0]


def u32(raw: bytes | mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<I", raw, offset)[0]


def u64(raw: bytes | mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<Q", raw, offset)[0]


def object_messages(raw: bytes, offset: int) -> list[tuple[int, bytes]]:
    if offset < 0 or offset + 16 > len(raw) or raw[offset] != 1:
        raise ValueError(f"unsupported or truncated object header at {offset}")
    message_count = u16(raw, offset + 2)
    chunk_size = u32(raw, offset + 8)
    cursor = offset + 16
    chunk_end = cursor + chunk_size
    if chunk_end > len(raw):
        raise ValueError("object-header chunk exceeds downloaded prefix")
    messages = []
    for _ in range(message_count):
        if cursor + 8 > chunk_end:
            raise ValueError("truncated object-header message")
        message_type = u16(raw, cursor)
        message_size = u16(raw, cursor + 2)
        payload_start = cursor + 8
        payload_end = payload_start + message_size
        if payload_end > chunk_end:
            raise ValueError("object-header message exceeds declared chunk")
        messages.append((message_type, raw[payload_start:payload_end]))
        cursor = payload_end
    return messages


def one_message(messages: list[tuple[int, bytes]], kind: int) -> bytes:
    found = [payload for message_type, payload in messages if message_type == kind]
    if len(found) != 1:
        raise ValueError(f"expected one HDF5 message type {kind}, found {len(found)}")
    return found[0]


def root_links(prefix: bytes) -> dict[str, int]:
    if prefix[:8] != HDF5_SIGNATURE or prefix[8] != 0:
        raise ValueError("source is not the expected HDF5 v0 file")
    if prefix[13:15] != b"\x08\x08" or u64(prefix, 24) != 0:
        raise ValueError("unexpected HDF5 address widths or base address")
    if u64(prefix, 40) != SOURCE_SIZE:
        raise ValueError("HDF5 end-of-file address changed")
    btree = u64(prefix, 80)
    heap = u64(prefix, 88)
    if prefix[btree:btree + 4] != b"TREE" or prefix[btree + 4] != 0:
        raise ValueError("unexpected root-group B-tree")
    if prefix[heap:heap + 4] != b"HEAP" or prefix[heap + 4] != 0:
        raise ValueError("unexpected root-group local heap")
    heap_data = u64(prefix, heap + 24)
    links = {}
    cursor = btree + 24
    for _ in range(u16(prefix, btree + 6)):
        child = u64(prefix, cursor + 8)
        if prefix[child:child + 4] != b"SNOD":
            raise ValueError("unexpected root-group symbol-table node")
        for index in range(u16(prefix, child + 6)):
            entry = child + 8 + index * 40
            name_start = heap_data + u64(prefix, entry)
            name_end = prefix.find(b"\0", name_start)
            if name_end < 0:
                raise ValueError("unterminated root-group link name")
            name = prefix[name_start:name_end].decode("ascii")
            links[name] = u64(prefix, entry + 8)
        cursor += 16
    return links


def source_layout(prefix: bytes) -> dict[str, object]:
    links = root_links(prefix)
    if set(links) != {"incident_energies", "showers"}:
        raise ValueError(f"unexpected root datasets: {sorted(links)}")
    result = {}
    for name, object_header in sorted(links.items()):
        messages = object_messages(prefix, object_header)
        dataspace = one_message(messages, 1)
        datatype = one_message(messages, 3)
        layout = one_message(messages, 8)
        filters = one_message(messages, 11)
        if dataspace[0] != 1 or dataspace[3] != 0:
            raise ValueError(f"{name}: unexpected simple dataspace")
        rank = dataspace[1]
        shape = struct.unpack_from("<" + "Q" * rank, dataspace, 8)
        if datatype[:len(H5T_IEEE_F64LE)] != H5T_IEEE_F64LE:
            raise ValueError(f"{name}: datatype is not H5T_IEEE_F64LE")
        if any(datatype[len(H5T_IEEE_F64LE):]):
            raise ValueError(f"{name}: nonzero datatype padding")
        if layout[:2] != b"\x03\x02":
            raise ValueError(f"{name}: dataset is not HDF5 v3 chunked layout")
        chunk_rank = layout[2] - 1
        chunk_shape = struct.unpack_from("<" + "I" * chunk_rank, layout, 11)
        if b"deflate\0" not in filters:
            raise ValueError(f"{name}: expected DEFLATE filter")
        result[name] = {
            "shape": tuple(shape),
            "chunk_shape": tuple(chunk_shape),
            "btree_address": u64(layout, 3),
        }
    if result["showers"]["shape"] != SOURCE_SHAPE:
        raise ValueError(f"showers shape changed: {result['showers']['shape']}")
    if result["showers"]["chunk_shape"] != CHUNK_SHAPE:
        raise ValueError(f"showers chunk shape changed: {result['showers']['chunk_shape']}")
    if result["incident_energies"]["shape"] != (100_000, 1):
        raise ValueError("incident_energies shape changed")
    return result


def btree_key(raw: bytes, offset: int, dimensions: int) -> dict[str, object]:
    return {
        "compressed_bytes": u32(raw, offset),
        "filter_mask": u32(raw, offset + 4),
        "offsets": tuple(
            struct.unpack_from("<" + "Q" * dimensions, raw, offset + 8)
        ),
    }


def parse_btree_node(raw: bytes, dimensions: int) -> dict[str, object]:
    if raw[:4] != b"TREE" or raw[4] != 1:
        raise ValueError("range is not an HDF5 raw-data chunk B-tree node")
    level = raw[5]
    entry_count = u16(raw, 6)
    key_size = 8 + dimensions * 8
    required = 24 + entry_count * (key_size + 8) + key_size
    if required > len(raw):
        raise ValueError(f"truncated B-tree node: need {required}, have {len(raw)}")
    cursor = 24
    entries = []
    for _ in range(entry_count):
        lower = btree_key(raw, cursor, dimensions)
        child = u64(raw, cursor + key_size)
        cursor += key_size + 8
        upper = btree_key(raw, cursor, dimensions)
        entries.append({"lower": lower, "child": child, "upper": upper})
    return {"level": level, "entries": entries, "required_bytes": required}


def load_prefix(download_dir: Path) -> bytes:
    path = download_dir / "prefix.bin"
    if not path.is_file() or path.stat().st_size != PREFIX_SIZE:
        raise SystemExit("missing or invalid 4 MiB HDF5 prefix")
    return path.read_bytes()


def node_data(download_dir: Path, prefix: bytes, address: int) -> bytes | None:
    if address + NODE_FETCH_BYTES <= len(prefix):
        return prefix[address:address + NODE_FETCH_BYTES]
    path = download_dir / "nodes" / f"node_{address}.bin"
    if not path.is_file() or path.stat().st_size != NODE_FETCH_BYTES:
        return None
    return path.read_bytes()


def plan_chunks(download_dir: Path, event_count: int) -> tuple[dict[str, object], list[dict[str, int]], set[int]]:
    if event_count <= 0 or event_count > SOURCE_SHAPE[0] or event_count % CHUNK_SHAPE[0]:
        raise SystemExit(
            f"event count must be a positive multiple of {CHUNK_SHAPE[0]} "
            f"and no greater than {SOURCE_SHAPE[0]}"
        )
    prefix = load_prefix(download_dir)
    try:
        layout = source_layout(prefix)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    root = int(layout["showers"]["btree_address"])
    dimensions = 3
    target_start = (0, 0, 0)
    target_end = (event_count, 0, 0)
    missing: set[int] = set()
    chunks: list[dict[str, int]] = []
    visited: set[int] = set()

    def visit(address: int, expected_level: int | None = None) -> None:
        if address in visited:
            raise ValueError(f"duplicate/cyclic B-tree node address: {address}")
        visited.add(address)
        raw = node_data(download_dir, prefix, address)
        if raw is None:
            missing.add(address)
            return
        node = parse_btree_node(raw, dimensions)
        level = int(node["level"])
        if expected_level is not None and level != expected_level:
            raise ValueError(f"B-tree level mismatch at {address}: {level} != {expected_level}")
        for entry in node["entries"]:
            lower = tuple(entry["lower"]["offsets"])
            upper = tuple(entry["upper"]["offsets"])
            if not (lower < target_end and upper > target_start):
                continue
            child = int(entry["child"])
            if level:
                visit(child, level - 1)
            elif lower[0] < event_count and lower[1] < SOURCE_SHAPE[1]:
                chunks.append({
                    "row_offset": int(lower[0]),
                    "column_offset": int(lower[1]),
                    "element_offset": int(lower[2]),
                    "source_offset": child,
                    "compressed_bytes": int(entry["lower"]["compressed_bytes"]),
                    "filter_mask": int(entry["lower"]["filter_mask"]),
                })

    try:
        visit(root)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    return layout, chunks, missing


def validate_chunk_grid(chunks: list[dict[str, int]], event_count: int) -> None:
    expected = {
        (row, column)
        for row in range(0, event_count, CHUNK_SHAPE[0])
        for column in range(0, SOURCE_SHAPE[1], CHUNK_SHAPE[1])
    }
    actual = {(chunk["row_offset"], chunk["column_offset"]) for chunk in chunks}
    if actual != expected or len(chunks) != len(actual):
        missing = sorted(expected - actual)[:5]
        extra = sorted(actual - expected)[:5]
        raise SystemExit(
            f"selected chunk grid mismatch count={len(chunks)} expected={len(expected)} "
            f"missing={missing} extra={extra}"
        )
    for chunk in chunks:
        if chunk["element_offset"] != 0 or chunk["filter_mask"] != 0:
            raise SystemExit(f"unexpected chunk offsets/filter mask: {chunk}")
        if chunk["compressed_bytes"] <= 0:
            raise SystemExit(f"invalid compressed chunk size: {chunk}")


def coalesce_ranges(chunks: list[dict[str, int]]) -> list[dict[str, int | str]]:
    spans = sorted(
        (chunk["source_offset"], chunk["source_offset"] + chunk["compressed_bytes"] - 1)
        for chunk in chunks
    )
    ranges: list[list[int]] = []
    for start, end in spans:
        if not ranges or start > ranges[-1][1] + 65_536 or end - ranges[-1][0] + 1 > 100_000_000:
            ranges.append([start, end])
        else:
            ranges[-1][1] = max(ranges[-1][1], end)
    result = [
        {
            "range_id": f"range_{index:03d}_{start}_{end}",
            "start": start,
            "end": end,
            "length": end - start + 1,
        }
        for index, (start, end) in enumerate(ranges)
    ]
    total = sum(int(item["length"]) for item in result)
    if total > 200_000_000:
        raise SystemExit(f"bounded compressed ranges exceed 200 MB: {total}")
    return result


def render_tsv(rows: list[dict[str, object]], fields: tuple[str, ...]) -> str:
    from io import StringIO
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def command_plan(args: argparse.Namespace) -> None:
    layout, chunks, missing = plan_chunks(args.download_dir, args.event_count)
    requests = [{"address": address, "length": NODE_FETCH_BYTES} for address in sorted(missing)]
    (args.download_dir / "node_requests.tsv").write_text(
        render_tsv(requests, ("address", "length")), encoding="utf-8"
    )
    if missing:
        print(f"missing_btree_nodes={len(missing)}")
        raise SystemExit(3)
    validate_chunk_grid(chunks, args.event_count)
    chunks.sort(key=lambda item: (item["row_offset"], item["column_offset"]))
    ranges = coalesce_ranges(chunks)
    (args.download_dir / "layout.json").write_text(
        json.dumps(
            {
                "source_shape": list(layout["showers"]["shape"]),
                "chunk_shape": list(layout["showers"]["chunk_shape"]),
                "chunk_btree_address": layout["showers"]["btree_address"],
                "selected_event_count": args.event_count,
                "selected_chunk_count": len(chunks),
                "selected_decoded_bytes": args.event_count * EVENT_BYTES,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    (args.download_dir / "chunk_plan.tsv").write_text(
        render_tsv(
            chunks,
            (
                "row_offset", "column_offset", "element_offset", "source_offset",
                "compressed_bytes", "filter_mask",
            ),
        ),
        encoding="utf-8",
    )
    (args.download_dir / "data_ranges.tsv").write_text(
        render_tsv(ranges, ("range_id", "start", "end", "length")),
        encoding="utf-8",
    )
    print(
        f"plan_complete events={args.event_count} chunks={len(chunks)} "
        f"ranges={len(ranges)} range_bytes={sum(int(r['length']) for r in ranges)}"
    )


def validate_record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise SystemExit("missing Zenodo record metadata")
    record = json.loads(path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    if int(record.get("id", 0)) != RECORD_ID or metadata.get("doi") != DOI:
        raise SystemExit("Zenodo record identity mismatch")
    if metadata.get("title") != "Fast Calorimeter Simulation Challenge 2022 - Dataset 2":
        raise SystemExit("Zenodo record title changed")
    if metadata.get("license", {}).get("id", "").lower() != "cc-by-4.0":
        raise SystemExit("Zenodo record does not declare CC BY 4.0")
    matches = [item for item in record.get("files", []) if item.get("key") == SOURCE_NAME]
    if len(matches) != 1:
        raise SystemExit("target HDF5 file is missing or duplicated in Zenodo metadata")
    item = matches[0]
    if int(item.get("size", 0)) != SOURCE_SIZE or item.get("checksum") != f"md5:{SOURCE_MD5}":
        raise SystemExit("target HDF5 size or MD5 changed")
    return record


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def command_inventory(args: argparse.Namespace) -> None:
    validate_record(args.download_dir / "record.json")
    _layout, chunks, missing = plan_chunks(args.download_dir, args.event_count)
    if missing:
        raise SystemExit(f"missing B-tree nodes after download: {sorted(missing)}")
    validate_chunk_grid(chunks, args.event_count)
    ranges = read_tsv(args.download_dir / "data_ranges.tsv")
    records = []
    for row in ranges:
        path = args.download_dir / "ranges" / f"{row['range_id']}.bin"
        expected = int(row["length"])
        if not path.is_file() or path.stat().st_size != expected:
            raise SystemExit(f"missing or invalid range file: {path}")
        records.append({
            "range_id": row["range_id"],
            "start": int(row["start"]),
            "end": int(row["end"]),
            "size_bytes": expected,
            "sha256": file_hash(path),
        })
    inventory = {
        "dataset_id": DATASET_ID,
        "record_id": RECORD_ID,
        "doi": DOI,
        "license": "CC BY 4.0",
        "source_file": SOURCE_NAME,
        "source_size_bytes": SOURCE_SIZE,
        "source_md5": SOURCE_MD5,
        "selected_event_count": args.event_count,
        "selected_chunk_count": len(chunks),
        "downloaded_data_range_bytes": sum(item["size_bytes"] for item in records),
        "prefix_sha256": file_hash(args.download_dir / "prefix.bin"),
        "ranges": records,
    }
    (args.download_dir / "download_inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"inventory=ok events={args.event_count} chunks={len(chunks)} "
        f"range_bytes={inventory['downloaded_data_range_bytes']}"
    )


class RangeReader:
    def __init__(self, download_dir: Path, inventory: dict[str, object]) -> None:
        self.handles = []
        self.maps: list[tuple[int, int, mmap.mmap]] = []
        for row in inventory["ranges"]:
            path = download_dir / "ranges" / f"{row['range_id']}.bin"
            if not path.is_file() or path.stat().st_size != row["size_bytes"]:
                raise SystemExit(f"missing range file: {path}")
            if file_hash(path) != row["sha256"]:
                raise SystemExit(f"range SHA-256 mismatch: {path}")
            handle = path.open("rb")
            mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            self.handles.append(handle)
            self.maps.append((int(row["start"]), int(row["end"]), mapping))

    def read(self, address: int, size: int) -> bytes:
        end = address + size - 1
        for start, range_end, mapping in self.maps:
            if start <= address and end <= range_end:
                offset = address - start
                return bytes(mapping[offset:offset + size])
        raise ValueError(f"chunk {address}+{size} is absent from downloaded ranges")

    def close(self) -> None:
        for _start, _end, mapping in self.maps:
            mapping.close()
        for handle in self.handles:
            handle.close()


def validate_inventory(download_dir: Path) -> dict[str, object]:
    validate_record(download_dir / "record.json")
    path = download_dir / "download_inventory.json"
    if not path.is_file():
        raise SystemExit("missing download inventory")
    inventory = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "dataset_id": DATASET_ID,
        "record_id": RECORD_ID,
        "doi": DOI,
        "license": "CC BY 4.0",
        "source_file": SOURCE_NAME,
        "source_size_bytes": SOURCE_SIZE,
        "source_md5": SOURCE_MD5,
        "selected_event_count": DEFAULT_EVENT_COUNT,
    }
    for key, value in required.items():
        if inventory.get(key) != value:
            raise SystemExit(f"download inventory mismatch: {key}")
    if file_hash(download_dir / "prefix.bin") != inventory.get("prefix_sha256"):
        raise SystemExit("prefix SHA-256 mismatch")
    return inventory


def load_chunks(download_dir: Path, event_count: int) -> list[dict[str, int]]:
    _layout, chunks, missing = plan_chunks(download_dir, event_count)
    if missing:
        raise SystemExit(f"missing B-tree nodes: {sorted(missing)}")
    validate_chunk_grid(chunks, event_count)
    chunks.sort(key=lambda item: (item["row_offset"], item["column_offset"]))
    stored = [
        {key: int(value) for key, value in row.items()}
        for row in read_tsv(download_dir / "chunk_plan.tsv")
    ]
    if stored != chunks:
        raise SystemExit("stored chunk plan differs from fresh HDF5 B-tree traversal")
    return chunks


def profile_event(payload: bytes) -> dict[str, object]:
    values = array.array("d")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != EVENT_VALUES:
        raise ValueError("event value count mismatch")
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        raise ValueError("event contains non-finite or negative deposited energy")
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        raise ValueError("event payload is constant")
    return {
        "minimum": minimum,
        "maximum": maximum,
        "zero_count": values.count(0.0),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def scan_events(download_dir: Path, consumer=None) -> dict[str, object]:
    inventory = validate_inventory(download_dir)
    event_count = int(inventory["selected_event_count"])
    chunks = load_chunks(download_dir, event_count)
    by_row: dict[int, list[dict[str, int]]] = {}
    for chunk in chunks:
        by_row.setdefault(chunk["row_offset"], []).append(chunk)
    reader = RangeReader(download_dir, inventory)
    aggregate = hashlib.sha256()
    event_profiles = []
    seen_hashes = set()
    try:
        for row_offset in sorted(by_row):
            valid_rows = min(CHUNK_SHAPE[0], event_count - row_offset)
            block = bytearray(valid_rows * EVENT_BYTES)
            for chunk in sorted(by_row[row_offset], key=lambda item: item["column_offset"]):
                compressed = reader.read(chunk["source_offset"], chunk["compressed_bytes"])
                try:
                    decoded = zlib.decompress(compressed)
                except zlib.error as error:
                    raise SystemExit(f"DEFLATE failure at source offset {chunk['source_offset']}: {error}") from error
                expected_decoded = CHUNK_SHAPE[0] * CHUNK_SHAPE[1] * 8
                if len(decoded) != expected_decoded:
                    raise SystemExit(
                        f"chunk decoded-size mismatch at {chunk['row_offset']},"
                        f"{chunk['column_offset']}: {len(decoded)} != {expected_decoded}"
                    )
                valid_columns = min(CHUNK_SHAPE[1], SOURCE_SHAPE[1] - chunk["column_offset"])
                copy_bytes = valid_columns * 8
                for local_row in range(valid_rows):
                    source_start = local_row * CHUNK_SHAPE[1] * 8
                    target_start = local_row * EVENT_BYTES + chunk["column_offset"] * 8
                    block[target_start:target_start + copy_bytes] = decoded[source_start:source_start + copy_bytes]
            for local_row in range(valid_rows):
                event_index = row_offset + local_row
                start = local_row * EVENT_BYTES
                payload = bytes(block[start:start + EVENT_BYTES])
                try:
                    profile = profile_event(payload)
                except ValueError as error:
                    raise SystemExit(f"event {event_index}: {error}") from error
                if profile["sha256"] in seen_hashes:
                    raise SystemExit(f"duplicate event payload: {event_index}")
                seen_hashes.add(profile["sha256"])
                aggregate.update(payload)
                record = {"event_index": event_index, **profile}
                event_profiles.append(record)
                if consumer is not None:
                    consumer(event_index, payload, record)
    finally:
        reader.close()
    if len(event_profiles) != event_count:
        raise SystemExit(f"event count mismatch: {len(event_profiles)} != {event_count}")
    result = {
        "dataset_id": DATASET_ID,
        "record_id": RECORD_ID,
        "doi": DOI,
        "license": "CC BY 4.0",
        "source_file": SOURCE_NAME,
        "source_shape": list(SOURCE_SHAPE),
        "source_chunk_shape": list(CHUNK_SHAPE),
        "sample_count": event_count,
        "sample_shape": [EVENT_VALUES],
        "value_count": event_count * EVENT_VALUES,
        "total_size_bytes": event_count * EVENT_BYTES,
        "minimum": min(float(row["minimum"]) for row in event_profiles),
        "maximum": max(float(row["maximum"]) for row in event_profiles),
        "zero_count": sum(int(row["zero_count"]) for row in event_profiles),
        "aggregate_sha256": aggregate.hexdigest(),
        "event_profiles": event_profiles,
    }
    expected = {
        "sample_count": DEFAULT_EVENT_COUNT,
        "value_count": EXPECTED_VALUE_COUNT,
        "total_size_bytes": EXPECTED_OUTPUT_BYTES,
        "minimum": EXPECTED_MINIMUM,
        "maximum": EXPECTED_MAXIMUM,
        "zero_count": EXPECTED_ZERO_COUNT,
        "aggregate_sha256": EXPECTED_AGGREGATE_SHA256,
    }
    for key, value in expected.items():
        if result[key] != value:
            raise SystemExit(f"pinned aggregate mismatch: {key}={result[key]!r} expected={value!r}")
    return result


def command_build(args: argparse.Namespace) -> None:
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    output_dir = args.samples_dir / SERIES_ID
    output_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_rows = []

    def emit(event_index: int, payload: bytes, profile: dict[str, object]) -> None:
        output = output_dir / f"electron_shower_{event_index:06d}_cells6480.bin"
        output.write_bytes(payload)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": (args.download_dir / "download_inventory.json").relative_to(args.data_root).as_posix(),
            "source_file": SOURCE_NAME,
            "source_field": "showers",
            "source_event_index": event_index,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "value_count": EVENT_VALUES,
            "sample_size_bytes": EVENT_BYTES,
            "sample_format": "raw homogeneous little-endian float64 calorimeter-cell energy array",
            "sample_geometry": "segmented_calorimeter_shower_event_1d",
            "sample_rank": 1,
            "sample_shape": [EVENT_VALUES],
            "sample_axes": ["detector_cell_source_order"],
            "natural_record_kind": "complete_geant4_single_electron_calorimeter_shower",
            "detector_geometry": {"layers": 45, "radial_bins_per_layer": 9, "angular_bins_per_layer": 16},
            **{key: profile[key] for key in ("minimum", "maximum", "zero_count", "sha256")},
        })

    summary = scan_events(args.download_dir, emit)
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"built_samples={summary['sample_count']} values={summary['value_count']} "
        f"bytes={summary['total_size_bytes']}"
    )


def command_verify(args: argparse.Namespace) -> None:
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing sample index or ingest stats")
    indexed = [
        json.loads(line)
        for line in args.index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    stored_stats = json.loads(args.stats.read_text(encoding="utf-8"))
    cursor = 0
    expected_outputs = set()

    def compare(event_index: int, payload: bytes, profile: dict[str, object]) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than source events")
        row = indexed[cursor]
        cursor += 1
        required = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "source_file": SOURCE_NAME,
            "source_field": "showers",
            "source_event_index": event_index,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "value_count": EVENT_VALUES,
            "sample_size_bytes": EVENT_BYTES,
            "sample_shape": [EVENT_VALUES],
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "zero_count": profile["zero_count"],
            "sha256": profile["sha256"],
        }
        for key, expected in required.items():
            if row.get(key) != expected:
                raise SystemExit(f"sample index mismatch event={event_index} field={key}")
        output = args.data_root / str(row.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"sample differs from fresh HDF5 extraction: {output}")
        expected_outputs.add(output.resolve())

    fresh = scan_events(args.download_dir, compare)
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if fresh != stored_stats:
        raise SystemExit("ingest stats differ from fresh source scan")
    print(
        f"verified_samples={fresh['sample_count']} values={fresh['value_count']} "
        f"bytes={fresh['total_size_bytes']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "inventory", "build", "verify"))
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--event-count", type=int, default=DEFAULT_EVENT_COUNT)
    parser.add_argument("--samples-dir", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if args.command == "plan":
        command_plan(args)
    elif args.command == "inventory":
        command_inventory(args)
    elif args.command == "build":
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("build requires --samples-dir, --index, --stats, and --data-root")
        command_build(args)
    else:
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("verify requires --samples-dir, --index, --stats, and --data-root")
        command_verify(args)


if __name__ == "__main__":
    main()
