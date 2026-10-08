#!/usr/bin/env python3
"""Synthetic self-test for cnc_h5.py.

A minimal pure-Python HDF5 writer emits files with the same structural
vocabulary as the upstream CNC_Machining files (superblock v0, symbol-table
root group, version-1 object headers, chunked layout v3 with a version-1
chunk B-tree, deflate filter), plus harder variants the real files do not use
but the reader claims to support: continuation messages, multi-level chunk
B-trees, partial edge chunks, multi-column chunks, the shuffle filter, and
per-chunk filter masks.  Each decoded payload must equal the C-order bytes of
the generated array exactly.  Unsupported features (fletcher32, big-endian,
missing chunks, unsigned integers) must be rejected.

Run: python3 selftest_cnc_h5.py
"""
from __future__ import annotations

import array
import random
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cnc_h5  # noqa: E402

UNDEF = 0xFFFFFFFFFFFFFFFF


def pad8(data: bytes) -> bytes:
    return data + b"\x00" * (-len(data) % 8)


class Writer:
    def __init__(self) -> None:
        self.buf = bytearray(96)  # superblock placeholder

    def alloc(self, data: bytes) -> int:
        while len(self.buf) % 8:
            self.buf.append(0)
        address = len(self.buf)
        self.buf += data
        return address

    def reserve(self, size: int) -> int:
        return self.alloc(b"\x00" * size)

    def put(self, address: int, data: bytes) -> None:
        self.buf[address : address + len(data)] = data


def message(mtype: int, body: bytes, flags: int = 0) -> bytes:
    body = pad8(body)
    return struct.pack("<HHB3x", mtype, len(body), flags) + body


def object_header(messages: list[bytes], nmsgs: int) -> bytes:
    block = b"".join(messages)
    return struct.pack("<BBHII", 1, 0, nmsgs, 1, len(block)) + b"\x00" * 4 + block


def dataspace(shape: tuple[int, ...]) -> bytes:
    body = struct.pack("<BBBB4x", 1, len(shape), 1, 0)
    body += struct.pack(f"<{len(shape)}Q", *shape) + struct.pack(f"<{len(shape)}Q", *shape)
    return body


def datatype(typecode: str, big_endian: bool = False, unsigned: bool = False) -> bytes:
    if typecode in "fd":
        size = 4 if typecode == "f" else 8
        precision, exp_loc, exp_size, mant_loc, mant_size, bias, sign = {
            4: (32, 23, 8, 0, 23, 127, 31),
            8: (64, 52, 11, 0, 52, 1023, 63),
        }[size]
        bits0 = 0x20 | (0x01 if big_endian else 0)
        return struct.pack("<BBBBI", 0x11, bits0, sign, 0, size) + struct.pack(
            "<HHBBBBI", 0, precision, exp_loc, exp_size, mant_loc, mant_size, bias
        )
    size = {"b": 1, "h": 2, "i": 4, "q": 8}[typecode]
    bits0 = (0x00 if unsigned else 0x08) | (0x01 if big_endian else 0)
    return struct.pack("<BBBBI", 0x10, bits0, 0, 0, size) + struct.pack("<HH", 0, 8 * size)


def filter_pipeline(filters: list[tuple[int, str, tuple[int, ...]]]) -> bytes:
    body = struct.pack("<BB6x", 1, len(filters))
    for filter_id, name, values in filters:
        name_bytes = pad8(name.encode() + b"\x00")
        body += struct.pack("<HHHH", filter_id, len(name_bytes), 0, len(values)) + name_bytes
        body += struct.pack(f"<{len(values)}I", *values)
        if len(values) % 2:
            body += b"\x00" * 4
    return body


def chunk_btree(w: Writer, entries: list[tuple[int, int, tuple[int, ...], int]], ndims: int, fanout: int) -> int:
    """Write a (possibly multi-level) node-type-1 B-tree; return root address."""
    key_size = 8 + 8 * ndims

    def key(stored: int, mask: int, offsets: tuple[int, ...]) -> bytes:
        return struct.pack("<II", stored, mask) + struct.pack(f"<{ndims}Q", *offsets)

    final_key = key(0, 0, tuple([1 << 40] * (ndims - 1) + [0]))
    level_nodes: list[tuple[bytes, int]] = []  # (first key, address)
    level = 0
    items = [(key(s, m, o), a) for s, m, o, a in entries]
    while True:
        groups = [items[i : i + fanout] for i in range(0, len(items), fanout)]
        level_nodes = []
        for group in groups:
            body = b"TREE" + struct.pack("<BBH", 1, level, len(group)) + struct.pack("<QQ", UNDEF, UNDEF)
            for k, child in group:
                body += k + struct.pack("<Q", child)
            body += final_key
            assert len(body) == 24 + len(group) * (key_size + 8) + key_size
            level_nodes.append((group[0][0], w.alloc(body)))
        if len(level_nodes) == 1:
            return level_nodes[0][1]
        items = level_nodes
        level += 1


def shuffle(data: bytes, es: int) -> bytes:
    count = len(data) // es
    out = bytearray(len(data))
    for b in range(es):
        out[b * count : (b + 1) * count] = data[b : count * es : es]
    out[count * es :] = data[count * es :]
    return bytes(out)


def make_file(values: list, shape: tuple[int, int], typecode: str, chunk: tuple[int, int], *,
              filters: str = "deflate", fanout: int = 64, continuation: bool = False,
              skip_filter_on_first_chunk: bool = False, drop_chunk: bool = False,
              big_endian: bool = False, unsigned: bool = False, extra_filter: int | None = None,
              name: str = "vibration_data") -> bytes:
    rows, cols = shape
    es = array.array(typecode).itemsize
    full = array.array(typecode, values)
    assert len(full) == rows * cols
    w = Writer()
    # chunks
    filt_list: list[tuple[int, str, tuple[int, ...]]] = []
    if "shuffle" in filters:
        filt_list.append((2, "shuffle", (es,)))
    if "deflate" in filters:
        filt_list.append((1, "deflate", (6,)))
    if extra_filter is not None:
        filt_list.append((extra_filter, "other", ()))
    entries = []
    first = True
    for r0 in range(0, rows, chunk[0]):
        for c0 in range(0, cols, chunk[1]):
            if drop_chunk and (r0, c0) == (0, 0):
                continue
            block = array.array(typecode, [0] * (chunk[0] * chunk[1]))
            for i in range(chunk[0]):
                for j in range(chunk[1]):
                    if r0 + i < rows and c0 + j < cols:
                        block[i * chunk[1] + j] = full[(r0 + i) * cols + c0 + j]
            data = block.tobytes()
            mask = 0
            if skip_filter_on_first_chunk and first:
                mask = (1 << len(filt_list)) - 1  # store raw
            else:
                for idx, (fid, _n, _v) in enumerate(filt_list):
                    if fid == 2:
                        data = shuffle(data, es)
                    elif fid == 1:
                        data = zlib.compress(data, 6)
            first = False
            entries.append((len(data), mask, (r0, c0, 0), w.alloc(data)))
    btree = chunk_btree(w, entries, 3, fanout)
    # dataset object header
    layout = struct.pack("<BBBQ", 3, 2, 3, btree) + struct.pack("<3I", chunk[0], chunk[1], es)
    dt = datatype(typecode, big_endian, unsigned)
    msgs_main = [message(1, dataspace(shape)), message(3, dt, 1),
                 message(5, struct.pack("<BBBBI", 2, 3, 0, 1, 0))]
    if filt_list:
        msgs_main.append(message(0x0B, filter_pipeline(filt_list)))
    tail = [message(8, layout), message(0x12, struct.pack("<B3xI", 1, 1600000000))]
    if continuation:
        cont_block = b"".join(tail)
        cont_addr = w.alloc(cont_block)
        msgs = msgs_main + [message(0x10, struct.pack("<QQ", cont_addr, len(cont_block)))]
        nmsgs = len(msgs) + len(tail)
    else:
        msgs = msgs_main + tail
        nmsgs = len(msgs)
    ds_addr = w.alloc(object_header(msgs, nmsgs))
    # local heap + SNOD + group B-tree
    heap_data = pad8(b"\x00" * 8 + name.encode() + b"\x00")
    heap_data_addr = w.alloc(heap_data)
    heap_addr = w.alloc(b"HEAP" + b"\x00" * 4 + struct.pack("<QQQ", len(heap_data), UNDEF, heap_data_addr))
    snod = b"SNOD" + struct.pack("<BBH", 1, 0, 1) + struct.pack("<QQII16x", 8, ds_addr, 0, 0)
    snod_addr = w.alloc(snod)
    gtree = b"TREE" + struct.pack("<BBH", 0, 0, 1) + struct.pack("<QQ", UNDEF, UNDEF)
    gtree += struct.pack("<QQQ", 0, snod_addr, 8)
    gtree_addr = w.alloc(gtree)
    root_oh = w.alloc(object_header([message(0x11, struct.pack("<QQ", gtree_addr, heap_addr))], 1))
    while len(w.buf) % 8:
        w.buf.append(0)
    eof = len(w.buf)
    sb = b"\x89HDF\r\n\x1a\n" + struct.pack("<8B", 0, 0, 0, 0, 0, 8, 8, 0)
    sb += struct.pack("<HHI", 4, 16, 0) + struct.pack("<4Q", 0, UNDEF, eof, UNDEF)
    sb += struct.pack("<QQII", 0, root_oh, 1, 0) + struct.pack("<QQ", gtree_addr, heap_addr)
    assert len(sb) == 96
    w.put(0, sb)
    return bytes(w.buf)


def expect_ok(label: str, values: list, shape: tuple[int, int], typecode: str, **kw) -> None:
    data = make_file(values, shape, typecode, **kw)
    decoded = cnc_h5.decode_file(data)
    want = array.array(typecode, values).tobytes()
    assert decoded.dataset.shape == shape, (label, decoded.dataset.shape)
    assert decoded.dataset.typecode == typecode, (label, decoded.dataset.typecode)
    assert decoded.raw == want, f"{label}: decoded bytes differ"
    assert decoded.root_links == ["vibration_data"], label
    print(f"ok   {label}: shape={shape} type={typecode} chunks={decoded.chunk_count} "
          f"continuations={decoded.dataset.continuation_count}")


def expect_fail(label: str, values: list, shape: tuple[int, int], typecode: str, needle: str, **kw) -> None:
    data = make_file(values, shape, typecode, **kw)
    try:
        cnc_h5.decode_file(data)
    except cnc_h5.H5Error as exc:
        assert needle in str(exc), f"{label}: unexpected error {exc}"
        print(f"ok   {label}: rejected ({exc})")
        return
    raise AssertionError(f"{label}: malformed file was accepted")


def main() -> int:
    rng = random.Random(20261006)
    rows = 10_007
    ints = [rng.randint(-32768, 32767) for _ in range(rows * 3)]
    floats = [float(v) for v in ints]
    expect_ok("float32 column chunks deflate", floats, (rows, 3), "f", chunk=(3350, 1))
    expect_ok("float64 column chunks deflate", floats, (rows, 3), "d", chunk=(2752, 1))
    expect_ok("int64 column chunks deflate", ints, (rows, 3), "q", chunk=(2496, 1))
    expect_ok("int64 multi-level btree", ints, (rows, 3), "q", chunk=(97, 1), fanout=8)
    expect_ok("float64 continuation message", floats, (rows, 3), "d", chunk=(1000, 1), continuation=True)
    expect_ok("float32 2-column chunks edge", floats, (rows, 3), "f", chunk=(333, 2))
    expect_ok("float64 shuffle+deflate", floats, (rows, 3), "d", chunk=(1500, 1), filters="shuffle+deflate")
    expect_ok("int64 filter mask raw chunk", ints, (rows, 3), "q", chunk=(4096, 1), skip_filter_on_first_chunk=True)
    expect_ok("float32 unfiltered chunks", floats, (rows, 3), "f", chunk=(4096, 3), filters="")
    expect_ok("float64 single chunk", floats[:30], (10, 3), "d", chunk=(2752, 1))
    expect_fail("fletcher32 rejected", floats, (rows, 3), "f", "unsupported HDF5 filter id 3", chunk=(3350, 1), extra_filter=3)
    expect_fail("big-endian rejected", floats, (rows, 3), "d", "not little-endian", chunk=(3350, 1), big_endian=True)
    expect_fail("unsigned rejected", [abs(v) for v in ints], (rows, 3), "q", "unsigned", chunk=(3350, 1), unsigned=True)
    expect_fail("missing chunk rejected", ints, (rows, 3), "q", "chunk grid mismatch", chunk=(3350, 1), drop_chunk=True)
    expect_fail("wrong dataset name rejected", ints, (rows, 3), "q", "lacks 'vibration_data'", chunk=(3350, 1), name="other")
    print("selftest passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
