#!/usr/bin/env python3
"""Validate one LoDoPaB HDF5 shard using only the Python standard library."""

from __future__ import annotations

import array
import hashlib
import json
import math
import mmap
from pathlib import Path
import struct
import sys


CANDIDATE_ID = "zenodo_lodopab_ct_sinograms_f32"
SOURCE_NAME = "observation_validation_000.hdf5"
SOURCE_SIZE = 272735288
SOURCE_SHA256 = "04f0399b1d1d4ff8d012d54312b1b67f84a412d94bf935865963172e996fb977"
SOURCE_SHAPE = (128, 1000, 513)
CHUNK_SHAPE = (8, 63, 33)
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
H5T_IEEE_F32LE = bytes.fromhex("11201f000400000000002000170800177f000000")


def u16(raw: bytes | mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<H", raw, offset)[0]


def u32(raw: bytes | mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<I", raw, offset)[0]


def u64(raw: bytes | mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<Q", raw, offset)[0]


def object_messages(raw: mmap.mmap, offset: int) -> list[tuple[int, bytes]]:
    if offset < 0 or offset + 16 > len(raw) or raw[offset] != 1:
        raise ValueError(f"unsupported or truncated object header at {offset}")
    message_count = u16(raw, offset + 2)
    chunk_size = u32(raw, offset + 8)
    cursor = offset + 16
    chunk_end = cursor + chunk_size
    if chunk_end > len(raw):
        raise ValueError("object-header chunk exceeds file")
    messages: list[tuple[int, bytes]] = []
    for _ in range(message_count):
        if cursor + 8 > chunk_end:
            raise ValueError("truncated object-header message")
        message_type = u16(raw, cursor)
        message_size = u16(raw, cursor + 2)
        payload_start = cursor + 8
        payload_end = payload_start + message_size
        if payload_end > chunk_end:
            raise ValueError("object-header message exceeds declared chunk")
        messages.append((message_type, bytes(raw[payload_start:payload_end])))
        cursor = payload_end
    return messages


def one_message(messages: list[tuple[int, bytes]], kind: int) -> bytes:
    found = [payload for message_type, payload in messages if message_type == kind]
    if len(found) != 1:
        raise ValueError(f"expected one HDF5 message type {kind}, found {len(found)}")
    return found[0]


def root_links(raw: mmap.mmap) -> dict[str, int]:
    if raw[:8] != HDF5_SIGNATURE or raw[8] != 0:
        raise ValueError("source is not the expected HDF5 v0 file")
    if raw[13:15] != b"\x08\x08" or u64(raw, 24) != 0:
        raise ValueError("unexpected HDF5 address widths or base address")
    if u64(raw, 40) != SOURCE_SIZE:
        raise ValueError(f"HDF5 end-of-file address changed: {u64(raw, 40)}")
    btree = u64(raw, 80)
    heap = u64(raw, 88)
    if raw[btree : btree + 4] != b"TREE" or raw[btree + 4] != 0:
        raise ValueError("unexpected root-group B-tree")
    if raw[heap : heap + 4] != b"HEAP" or raw[heap + 4] != 0:
        raise ValueError("unexpected root-group local heap")
    heap_data = u64(raw, heap + 24)
    links: dict[str, int] = {}
    cursor = btree + 24
    for _ in range(u16(raw, btree + 6)):
        child = u64(raw, cursor + 8)
        if raw[child : child + 4] != b"SNOD":
            raise ValueError("unexpected root-group symbol-table node")
        for index in range(u16(raw, child + 6)):
            entry = child + 8 + index * 40
            name_start = heap_data + u64(raw, entry)
            name_end = raw.find(b"\0", name_start)
            if name_end < 0:
                raise ValueError("unterminated root-group link name")
            name = raw[name_start:name_end].decode("ascii")
            links[name] = u64(raw, entry + 8)
        cursor += 16
    return links


def source_layout(raw: mmap.mmap) -> dict[str, object]:
    links = root_links(raw)
    if set(links) != {"data"}:
        raise ValueError(f"unexpected root datasets: {sorted(links)}")
    messages = object_messages(raw, links["data"])
    dataspace = one_message(messages, 1)
    datatype = one_message(messages, 3)
    layout = one_message(messages, 8)
    filters = [payload for message_type, payload in messages if message_type == 11]
    if dataspace[0] != 1 or dataspace[1] != 3 or dataspace[3] != 0:
        raise ValueError("unexpected HDF5 simple dataspace encoding")
    shape = struct.unpack_from("<QQQ", dataspace, 8)
    if shape != SOURCE_SHAPE:
        raise ValueError(f"source shape changed: {shape}")
    if datatype[: len(H5T_IEEE_F32LE)] != H5T_IEEE_F32LE:
        raise ValueError(f"dataset is not H5T_IEEE_F32LE: {datatype.hex()}")
    if any(datatype[len(H5T_IEEE_F32LE) :]):
        raise ValueError("nonzero HDF5 datatype padding")
    if layout[:3] != b"\x03\x02\x04":
        raise ValueError(f"unexpected HDF5 chunked-layout header: {layout[:3].hex()}")
    chunk_btree = u64(layout, 3)
    chunk_shape = struct.unpack_from("<III", layout, 11)
    element_size = u32(layout, 23)
    if chunk_shape != CHUNK_SHAPE or element_size != 4:
        raise ValueError(
            f"unexpected chunk layout: shape={chunk_shape} element_size={element_size}"
        )
    if filters:
        raise ValueError("unexpected HDF5 filter pipeline; source chunks should be unfiltered")
    return {
        "shape": shape,
        "chunk_shape": chunk_shape,
        "chunk_btree": chunk_btree,
        "datatype": "H5T_IEEE_F32LE",
    }


def btree_key(raw: mmap.mmap, offset: int, dimensions: int) -> dict[str, object]:
    return {
        "stored_bytes": u32(raw, offset),
        "filter_mask": u32(raw, offset + 4),
        "offsets": tuple(struct.unpack_from("<" + "Q" * dimensions, raw, offset + 8)),
    }


def parse_btree_node(raw: mmap.mmap, address: int, dimensions: int) -> dict[str, object]:
    if address < 0 or address + 24 > len(raw):
        raise ValueError(f"chunk B-tree address out of range: {address}")
    if raw[address : address + 4] != b"TREE" or raw[address + 4] != 1:
        raise ValueError(f"address {address} is not a raw-data chunk B-tree node")
    level = raw[address + 5]
    entry_count = u16(raw, address + 6)
    key_size = 8 + dimensions * 8
    required = 24 + entry_count * (key_size + 8) + key_size
    if address + required > len(raw):
        raise ValueError(f"truncated chunk B-tree node at {address}")
    cursor = address + 24
    entries = []
    for _ in range(entry_count):
        lower = btree_key(raw, cursor, dimensions)
        child = u64(raw, cursor + key_size)
        cursor += key_size + 8
        upper = btree_key(raw, cursor, dimensions)
        entries.append({"lower": lower, "child": child, "upper": upper})
    return {"level": level, "entries": entries}


def collect_chunks(raw: mmap.mmap, root: int) -> list[dict[str, object]]:
    dimensions = 4
    chunks: list[dict[str, object]] = []
    visited: set[int] = set()

    def visit(address: int, expected_level: int | None = None) -> None:
        if address in visited:
            raise ValueError(f"duplicate/cyclic B-tree node address: {address}")
        visited.add(address)
        node = parse_btree_node(raw, address, dimensions)
        level = int(node["level"])
        if expected_level is not None and level != expected_level:
            raise ValueError(f"B-tree level mismatch at {address}: {level} != {expected_level}")
        for entry in node["entries"]:
            if level:
                visit(int(entry["child"]), level - 1)
            else:
                lower = entry["lower"]
                chunks.append(
                    {
                        "offsets": tuple(lower["offsets"]),
                        "source_offset": int(entry["child"]),
                        "stored_bytes": int(lower["stored_bytes"]),
                        "filter_mask": int(lower["filter_mask"]),
                    }
                )

    visit(root)
    return chunks


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    source = repo_root / ".data" / "downloads" / CANDIDATE_ID / SOURCE_NAME
    output = repo_root / ".data" / "discovery" / CANDIDATE_ID / "hdf5_probe.json"
    if not source.is_file() or source.stat().st_size != SOURCE_SIZE:
        raise SystemExit(f"missing or invalid probe HDF5: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    if digest.hexdigest() != SOURCE_SHA256:
        raise SystemExit(f"probe HDF5 SHA-256 changed: {digest.hexdigest()}")

    with source.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        layout = source_layout(raw)
        chunks = collect_chunks(raw, int(layout["chunk_btree"]))
        expected_offsets = {
            (sample, angle, detector, 0)
            for sample in range(0, SOURCE_SHAPE[0], CHUNK_SHAPE[0])
            for angle in range(0, SOURCE_SHAPE[1], CHUNK_SHAPE[1])
            for detector in range(0, SOURCE_SHAPE[2], CHUNK_SHAPE[2])
        }
        actual_offsets = {tuple(chunk["offsets"]) for chunk in chunks}
        if actual_offsets != expected_offsets or len(chunks) != len(actual_offsets):
            raise ValueError(
                f"chunk grid mismatch: expected={len(expected_offsets)} actual={len(chunks)}"
            )
        chunk_bytes = math.prod(CHUNK_SHAPE) * 4
        sample_minimum = [math.inf] * SOURCE_SHAPE[0]
        sample_maximum = [-math.inf] * SOURCE_SHAPE[0]
        total_values = 0
        zero_values = 0
        global_minimum = math.inf
        global_maximum = -math.inf
        for chunk_number, chunk in enumerate(sorted(chunks, key=lambda item: item["offsets"]), 1):
            offsets = tuple(int(value) for value in chunk["offsets"])
            source_offset = int(chunk["source_offset"])
            stored_bytes = int(chunk["stored_bytes"])
            if int(chunk["filter_mask"]) != 0 or stored_bytes != chunk_bytes:
                raise ValueError(f"unexpected unfiltered chunk metadata: {chunk}")
            if source_offset < 0 or source_offset + stored_bytes > len(raw):
                raise ValueError(f"chunk payload exceeds source file: {chunk}")
            payload = raw[source_offset : source_offset + stored_bytes]
            values = array.array("f")
            values.frombytes(payload)
            if sys.byteorder != "little":
                values.byteswap()
            sample_base, angle_base, detector_base, element_offset = offsets
            if element_offset != 0:
                raise ValueError(f"unexpected element offset: {offsets}")
            valid_samples = min(CHUNK_SHAPE[0], SOURCE_SHAPE[0] - sample_base)
            valid_angles = min(CHUNK_SHAPE[1], SOURCE_SHAPE[1] - angle_base)
            valid_detectors = min(CHUNK_SHAPE[2], SOURCE_SHAPE[2] - detector_base)
            for local_sample in range(valid_samples):
                sample_index = sample_base + local_sample
                for local_angle in range(valid_angles):
                    start = (local_sample * CHUNK_SHAPE[1] + local_angle) * CHUNK_SHAPE[2]
                    row = values[start : start + valid_detectors]
                    if not row or not all(math.isfinite(value) for value in row):
                        raise ValueError(
                            f"empty or non-finite values in chunk={offsets} sample={sample_index}"
                        )
                    row_minimum = min(row)
                    row_maximum = max(row)
                    sample_minimum[sample_index] = min(sample_minimum[sample_index], row_minimum)
                    sample_maximum[sample_index] = max(sample_maximum[sample_index], row_maximum)
                    global_minimum = min(global_minimum, row_minimum)
                    global_maximum = max(global_maximum, row_maximum)
                    zero_values += sum(value == 0.0 for value in row)
                    total_values += len(row)
            if chunk_number % 512 == 0:
                print(f"chunks_scanned={chunk_number}/{len(chunks)}", file=sys.stderr, flush=True)

    expected_values = math.prod(SOURCE_SHAPE)
    if total_values != expected_values:
        raise ValueError(f"valid value count mismatch: expected={expected_values} actual={total_values}")
    constant_samples = [
        index
        for index, (minimum, maximum) in enumerate(zip(sample_minimum, sample_maximum))
        if minimum == maximum
    ]
    if constant_samples:
        raise ValueError(f"constant sinograms found: {constant_samples[:10]}")
    summary = {
        "candidate_id": CANDIDATE_ID,
        "source_name": SOURCE_NAME,
        "source_bytes": SOURCE_SIZE,
        "source_sha256": SOURCE_SHA256,
        "dataset_path": "data",
        "dtype": "little-endian IEEE float32",
        "shape": list(SOURCE_SHAPE),
        "chunk_shape": list(CHUNK_SHAPE),
        "chunk_count": len(chunks),
        "natural_samples": SOURCE_SHAPE[0],
        "values_per_sample": SOURCE_SHAPE[1] * SOURCE_SHAPE[2],
        "bytes_per_sample": SOURCE_SHAPE[1] * SOURCE_SHAPE[2] * 4,
        "total_values": total_values,
        "decoded_float32_bytes": total_values * 4,
        "minimum": global_minimum,
        "maximum": global_maximum,
        "zero_values": zero_values,
        "zero_fraction": zero_values / total_values,
        "constant_samples": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError, struct.error) as exc:
        raise SystemExit(f"probe failed: {exc}") from exc
