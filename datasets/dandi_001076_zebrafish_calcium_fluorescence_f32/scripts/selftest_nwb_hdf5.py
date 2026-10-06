#!/usr/bin/env python3
"""Synthetic end-to-end self-test for nwb_hdf5.py (standard library only).

Writes tiny HDF5 files byte by byte (superblock v0, v1 object headers with a
continuation block, symbol-table groups behind a two-level group B-tree, a soft
link, a variable-length string attribute in a global heap, and a chunked
deflate float32 dataset with edge-chunk padding), then checks that the reader
reproduces the exact logical matrix and rejects corrupted variants.
"""

from __future__ import annotations

import array
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nwb_hdf5 as H  # noqa: E402

UNDEF = 0xFFFFFFFFFFFFFFFF
F32LE = H.H5T_IEEE_F32LE
F32BE = bytes([0x11, 0x21]) + F32LE[2:]


def pad8(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 8)


class Writer:
    def __init__(self) -> None:
        self.buf = bytearray(96)  # superblock placeholder

    def add(self, data: bytes) -> int:
        self.buf += b"\0" * (-len(self.buf) % 8)
        address = len(self.buf)
        self.buf += data
        return address

    def reserve(self, size: int) -> int:
        return self.add(b"\0" * size)

    def put(self, address: int, data: bytes) -> None:
        self.buf[address : address + len(data)] = data


def message(kind: int, payload: bytes) -> bytes:
    payload = pad8(payload)
    return struct.pack("<HHB3x", kind, len(payload), 0) + payload


def object_header(w: Writer, messages: list[tuple[int, bytes]], split: int | None = None) -> int:
    """Write a v1 object header; messages from ``split`` on go to a continuation block."""
    if split is None:
        body = b"".join(message(k, p) for k, p in messages)
        count = len(messages)
        return w.add(struct.pack("<BBHII4x", 1, 0, count, 1, len(body)) + body)
    tail = b"".join(message(k, p) for k, p in messages[split:])
    tail_address = w.add(tail)
    head = b"".join(message(k, p) for k, p in messages[:split])
    head += message(H.MSG_CONTINUATION, struct.pack("<QQ", tail_address, len(tail)))
    count = len(messages) + 1
    return w.add(struct.pack("<BBHII4x", 1, 0, count, 1, len(head)) + head)


def local_heap(w: Writer, names: list[str]) -> tuple[int, dict[str, int]]:
    data = bytearray(8)  # offset 0 is the empty name
    offsets = {}
    for name in names:
        offsets[name] = len(data)
        data += pad8(name.encode() + b"\0")
    data_address = w.add(bytes(data))
    header = b"HEAP" + bytes([0, 0, 0, 0]) + struct.pack("<QQQ", len(data), UNDEF, data_address)
    return w.add(header), offsets


def group(w: Writer, entries: list[tuple[str, int | None]], two_level: bool = False) -> tuple[int, int]:
    """Write heap + group B-tree + SNODs; return (btree address, heap address)."""
    entries = sorted(entries)
    heap, offsets = local_heap(w, [name for name, _ in entries])

    def snod(chunk: list[tuple[str, int | None]]) -> int:
        body = bytearray(b"SNOD" + bytes([1, 0]) + struct.pack("<H", len(chunk)))
        for name, address in chunk:
            if address is None:  # soft link: cache type 2, undefined header address
                body += struct.pack("<QQII16s", offsets[name], UNDEF, 2, 0, b"\0" * 16)
            else:
                body += struct.pack("<QQII16s", offsets[name], address, 0, 0, b"\0" * 16)
        return w.add(bytes(body))

    def leaf(chunk: list[tuple[str, int | None]]) -> int:
        if not chunk:  # empty group: zero-entry leaf with only the first key
            return w.add(b"TREE" + bytes([0, 0]) + struct.pack("<HQQQ", 0, UNDEF, UNDEF, 0))
        child = snod(chunk)
        node = b"TREE" + bytes([0, 0]) + struct.pack("<HQQ", 1, UNDEF, UNDEF)
        node += struct.pack("<QQQ", 0, child, offsets[chunk[-1][0]])
        return w.add(node)

    if not two_level or len(entries) < 2:
        return leaf(entries), heap
    half = len(entries) // 2
    left, right = leaf(entries[:half]), leaf(entries[half:])
    node = b"TREE" + bytes([0, 1]) + struct.pack("<HQQ", 2, UNDEF, UNDEF)
    node += struct.pack("<QQQQQ", 0, left, offsets[entries[half - 1][0]], right, offsets[entries[-1][0]])
    return w.add(node), heap


def group_header(w: Writer, entries: list[tuple[str, int | None]]) -> int:
    btree, heap = group(w, entries)
    return object_header(w, [(H.MSG_SYMBOL_TABLE, struct.pack("<QQ", btree, heap))])


def attribute(name: str, dtype: bytes, data: bytes) -> bytes:
    raw_name = name.encode() + b"\0"
    space = bytes([1, 0, 0, 0, 0, 0, 0, 0])  # v1 scalar
    return (
        struct.pack("<BBHHH", 1, 0, len(raw_name), len(dtype), len(space))
        + pad8(raw_name) + pad8(dtype) + pad8(space) + data
    )


def make_file(values: list[float], shape: tuple[int, int], chunk: tuple[int, int], mutate: str = "") -> bytes:
    w = Writer()
    rows, cols = shape
    crow, ccol = chunk
    # Global heap holding the vlen 'unit' string.
    unit = b"n.a."
    gcol_body = struct.pack("<HHIQ", 1, 1, 0, len(unit)) + pad8(unit)
    gcol_size = 16 + len(gcol_body) + 16
    gcol = w.add(b"GCOL" + bytes([1, 0, 0, 0]) + struct.pack("<Q", gcol_size) + gcol_body
                 + struct.pack("<HHIQ", 0, 0, 0, 0))
    # Chunks: full-size (padded) row-major blocks, deflated.
    keys = []
    grid = [(r, c) for r in range(0, rows, crow) for c in range(0, cols, ccol)]
    if mutate == "missing_chunk":
        grid = grid[:-1]
    for r0, c0 in grid:
        block = array.array("f", [0.0] * (crow * ccol))
        for i in range(min(crow, rows - r0)):
            for j in range(min(ccol, cols - c0)):
                block[i * ccol + j] = values[(r0 + i) * cols + (c0 + j)]
        if sys.byteorder != "little":
            block.byteswap()
        stored = zlib.compress(block.tobytes(), 4)
        if mutate == "truncated_deflate" and (r0, c0) == grid[-1]:
            stored = stored[:-6]
        address = w.add(stored)
        mask = 1 if mutate == "filter_mask" and (r0, c0) == grid[0] else 0
        keys.append((struct.pack("<IIQQQ", len(stored), mask, r0, c0, 0), address))
    if mutate == "duplicate_chunk":
        keys.append(keys[0])
    end_key = struct.pack("<IIQQQ", 0, 0, rows, cols, 0)
    node = b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", len(keys), UNDEF, UNDEF)
    for key, address in keys:
        node += key + struct.pack("<Q", address)
    node += end_key
    chunk_btree = w.add(node)
    dtype = F32BE if mutate == "big_endian" else F32LE
    dataspace = struct.pack("<BBBB4xQQ", 1, 2, 0, 0, rows, cols)
    layout = struct.pack("<BBBQIII", 3, 2, 3, chunk_btree, crow, ccol, 4)
    deflate = struct.pack("<HHHH", 1, 8, 1, 1) + b"deflate\0" + struct.pack("<II", 4, 0)
    shuffle = struct.pack("<HHHH", 2, 8, 1, 1) + b"shuffle\0" + struct.pack("<II", 4, 0)
    filters = [shuffle, deflate] if mutate == "shuffle" else [deflate]
    pipeline = struct.pack("<BB6x", 1, len(filters)) + b"".join(filters)
    unit_attr = attribute("unit", bytes.fromhex("1901010010000000") + bytes.fromhex("13000000") + b"\x01\0\0\0",
                          struct.pack("<IQI", len(unit), gcol, 1))
    conversion_attr = attribute("conversion", F32LE, struct.pack("<f", 1.0))
    data_header = object_header(
        w,
        [(H.MSG_DATASPACE, dataspace), (H.MSG_DATATYPE, dtype), (H.MSG_LAYOUT, layout),
         (H.MSG_FILTER, pipeline), (H.MSG_ATTRIBUTE, unit_attr), (H.MSG_ATTRIBUTE, conversion_attr)],
        split=3,
    )
    rrs = group_header(w, [("data", data_header), ("rois", None)])
    fluorescence = group_header(w, [("RoiResponseSeries", rrs)])
    ophys = group_header(w, [("Fluorescence", fluorescence)])
    processing = group_header(w, [("ophys", ophys)])
    empty_a = group_header(w, [])
    empty_b = group_header(w, [])
    root_btree, root_heap = group(
        w, [("acquisition", empty_a), ("analysis", empty_b), ("processing", processing), ("specloc", None)],
        two_level=True,
    )
    root_header = object_header(w, [(H.MSG_SYMBOL_TABLE, struct.pack("<QQ", root_btree, root_heap))])
    w.buf += b"\0" * (-len(w.buf) % 8)
    superblock = (
        H.HDF5_SIGNATURE + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
        + struct.pack("<QQQQ", 0, UNDEF, len(w.buf), UNDEF)
        + struct.pack("<QQII", 0, root_header, 1, 0) + struct.pack("<QQ", root_btree, root_heap)
    )
    assert len(superblock) == 96
    w.put(0, superblock)
    return bytes(w.buf)


def expect_failure(label: str, payload: bytes) -> None:
    try:
        decode(payload)
    except ValueError as exc:
        print(f"selftest reject_ok case={label} reason={str(exc)[:80]!r}")
        return
    raise SystemExit(f"selftest FAILED: corrupted case {label!r} was accepted")


def decode(payload: bytes) -> tuple[bytes, dict[str, object]]:
    h5 = H.H5File(payload, len(payload))
    info = h5.dataset(h5.resolve("processing/ophys/Fluorescence/RoiResponseSeries/data"))
    data, _ = H.read_f32_deflate_2d(h5, info)
    return data, info


def main() -> int:
    for shape, chunk in (((5, 7), (3, 4)), ((6, 4), (6, 4)), ((4, 9), (4, 5))):
        rows, cols = shape
        values = [((r * 31 + c * 7) % 97) * 0.37 - 5.5 + r * 1e-3 for r in range(rows) for c in range(cols)]
        payload = make_file(values, shape, chunk)
        data, info = decode(payload)
        expected = array.array("f", values)
        if sys.byteorder != "little":
            expected.byteswap()
        if data != expected.tobytes():
            raise SystemExit(f"selftest FAILED: decoded matrix differs for shape={shape} chunk={chunk}")
        attrs = info["attributes"]
        if attrs.get("unit") != "n.a." or attrs.get("conversion") != 1.0:
            raise SystemExit(f"selftest FAILED: attributes decoded as {attrs}")
        h5 = H.H5File(payload, len(payload))
        root = h5.group_links(h5.root_header)
        if sorted(root) != ["acquisition", "analysis", "processing", "specloc"] or root["specloc"] is not None:
            raise SystemExit(f"selftest FAILED: root links {root}")
        print(f"selftest decode_ok shape={shape} chunk={chunk} bytes={len(data)}")
    values = [float(i) * 0.5 - 3.0 for i in range(35)]
    for case in ("missing_chunk", "duplicate_chunk", "filter_mask", "truncated_deflate", "big_endian", "shuffle"):
        expect_failure(case, make_file(values, (5, 7), (3, 4), mutate=case))
    good = make_file(values, (5, 7), (3, 4))
    expect_failure("bad_eof", good + b"\0" * 8)
    expect_failure("bad_signature", b"\0" + good[1:])
    print("selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
