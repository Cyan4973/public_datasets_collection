#!/usr/bin/env python3
"""Synthetic self-test for hypersim_h5.py and hypersim_zip.py.

HDF5: a minimal pure-Python writer emits files with the structural vocabulary
of the Hypersim G-buffer files (superblock v0, symbol-table root group holding
``dataset``, version-1 object headers, rank-3 float16 dataset, chunked layout
v3 with a version-1 chunk B-tree, deflate filter) plus harder variants the
real files do not use but the reader claims to support: partial edge chunks
in every dimension, multi-element last-dim chunks, multi-level chunk B-trees,
continuation messages, the shuffle filter, and per-chunk filter masks.  Each
decoded payload must equal the C-order bytes of the generated array exactly.
Unsupported features (fletcher32, big-endian, missing chunks, integer type,
wrong dataset name) must be rejected.

ZIP: stdlib ``zipfile`` writes stored archives (one forced into zip64 EOCD
records by having more than 65535 entries); the eocd/find/extract path must
recover each member byte-exactly from tail/CD/slab slices, reject a renamed
local header and a corrupted member, and a hand-built central directory entry
with a zip64 extra field must resolve its >4 GiB offset.

Run: python3 selftest.py
"""
from __future__ import annotations

import io
import random
import struct
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hypersim_h5  # noqa: E402
import hypersim_zip  # noqa: E402

UNDEF = 0xFFFFFFFFFFFFFFFF


def pad8(data: bytes) -> bytes:
    return data + b"\x00" * (-len(data) % 8)


class Writer:
    def __init__(self) -> None:
        self.buf = bytearray(96)

    def alloc(self, data: bytes) -> int:
        while len(self.buf) % 8:
            self.buf.append(0)
        address = len(self.buf)
        self.buf += data
        return address

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
    return body + struct.pack(f"<{len(shape)}Q", *shape) * 2


def datatype_f16(big_endian: bool = False, integer: bool = False) -> bytes:
    if integer:
        return struct.pack("<BBBBI", 0x10, 0x08, 0, 0, 2) + struct.pack("<HH", 0, 16)
    bits0 = 0x20 | (0x01 if big_endian else 0)
    # exactly the bytes seen in the real files: 11 20 0f 00 02000000 0000 1000 0a 05 00 0a 0f000000
    return struct.pack("<BBBBI", 0x11, bits0, 15, 0, 2) + struct.pack("<HHBBBBI", 0, 16, 10, 5, 0, 10, 15)


def filter_pipeline(filters: list[tuple[int, str, tuple[int, ...]]]) -> bytes:
    body = struct.pack("<BB6x", 1, len(filters))
    for filter_id, name, values in filters:
        name_bytes = pad8(name.encode() + b"\x00")
        body += struct.pack("<HHHH", filter_id, len(name_bytes), 1, len(values)) + name_bytes
        body += struct.pack(f"<{len(values)}I", *values)
        if len(values) % 2:
            body += b"\x00" * 4
    return body


def chunk_btree(w: Writer, entries, ndims: int, fanout: int) -> int:
    key_size = 8 + 8 * ndims

    def key(stored: int, mask: int, offsets) -> bytes:
        return struct.pack("<II", stored, mask) + struct.pack(f"<{ndims}Q", *offsets)

    final_key = key(0, 0, tuple([1 << 40] * (ndims - 1) + [0]))
    level = 0
    items = [(key(s, m, o), a) for s, m, o, a in entries]
    while True:
        nodes = []
        for i in range(0, len(items), fanout):
            group = items[i : i + fanout]
            body = b"TREE" + struct.pack("<BBH", 1, level, len(group)) + struct.pack("<QQ", UNDEF, UNDEF)
            for k, child in group:
                body += k + struct.pack("<Q", child)
            body += final_key
            assert len(body) == 24 + len(group) * (key_size + 8) + key_size
            nodes.append((group[0][0], w.alloc(body)))
        if len(nodes) == 1:
            return nodes[0][1]
        items = nodes
        level += 1


def shuffle(data: bytes, es: int) -> bytes:
    count = len(data) // es
    out = bytearray(len(data))
    for b in range(es):
        out[b * count : (b + 1) * count] = data[b : count * es : es]
    return bytes(out)


def make_file(words: list[int], shape, chunk, *, filters: str = "deflate", fanout: int = 64,
              continuation: bool = False, raw_first_chunk: bool = False, drop_chunk: bool = False,
              big_endian: bool = False, integer: bool = False, extra_filter: int | None = None,
              name: str = "dataset") -> bytes:
    es = 2
    d0, d1, d2 = shape
    assert len(words) == d0 * d1 * d2
    w = Writer()
    filt = []
    if "shuffle" in filters:
        filt.append((2, "shuffle", (es,)))
    if "deflate" in filters:
        filt.append((1, "deflate", (9,)))
    if extra_filter is not None:
        filt.append((extra_filter, "other", ()))
    entries = []
    first = True
    for a in range(0, d0, chunk[0]):
        for b in range(0, d1, chunk[1]):
            for c in range(0, d2, chunk[2]):
                if drop_chunk and (a, b, c) == (0, 0, 0):
                    continue
                block = [0] * (chunk[0] * chunk[1] * chunk[2])
                for i in range(chunk[0]):
                    for j in range(chunk[1]):
                        for k in range(chunk[2]):
                            if a + i < d0 and b + j < d1 and c + k < d2:
                                block[(i * chunk[1] + j) * chunk[2] + k] = words[((a + i) * d1 + b + j) * d2 + c + k]
                data = struct.pack(f"<{len(block)}H", *block)
                mask = 0
                if raw_first_chunk and first:
                    mask = (1 << len(filt)) - 1
                else:
                    for fid, _n, _v in filt:
                        if fid == 2:
                            data = shuffle(data, es)
                        elif fid == 1:
                            data = zlib.compress(data, 9)
                first = False
                entries.append((len(data), mask, (a, b, c, 0), w.alloc(data)))
    btree = chunk_btree(w, entries, 4, fanout)
    layout = struct.pack("<BBBQ", 3, 2, 4, btree) + struct.pack("<4I", *chunk, es)
    main = [message(1, dataspace(shape)), message(3, datatype_f16(big_endian, integer), 1),
            message(5, struct.pack("<BBBBI", 2, 3, 0, 1, 0), 1)]
    if filt:
        main.append(message(0x0B, filter_pipeline(filt), 1))
    tail = [message(8, layout), message(0x12, struct.pack("<B3xI", 1, 1582607456))]
    if continuation:
        block = b"".join(tail)
        addr = w.alloc(block)
        msgs = main + [message(0x10, struct.pack("<QQ", addr, len(block)))]
        nmsgs = len(msgs) + len(tail)
    else:
        msgs = main + tail
        nmsgs = len(msgs)
    ds_addr = w.alloc(object_header(msgs, nmsgs))
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
    sb = b"\x89HDF\r\n\x1a\n" + struct.pack("<8B", 0, 0, 0, 0, 0, 8, 8, 0)
    sb += struct.pack("<HHI", 4, 16, 0) + struct.pack("<4Q", 0, UNDEF, len(w.buf), UNDEF)
    sb += struct.pack("<QQII", 0, root_oh, 1, 0) + struct.pack("<QQ", gtree_addr, heap_addr)
    assert len(sb) == 96
    w.put(0, sb)
    return bytes(w.buf)


def random_words(rng: random.Random, n: int) -> list[int]:
    # finite float16 patterns plus a sprinkling of NaN payloads (0x7e00, 0xfe00)
    out = []
    for _ in range(n):
        r = rng.random()
        if r < 0.02:
            out.append(rng.choice((0x7E00, 0xFE00)))
        else:
            out.append(rng.randrange(0, 0x10000) & 0xFBFF)  # exponent never all-ones
    return out


def expect_ok(label: str, words, shape, chunk, **kw) -> None:
    data = make_file(words, shape, chunk, **kw)
    dec = hypersim_h5.decode_file(data)
    want = struct.pack(f"<{len(words)}H", *words)
    assert dec.dataset.shape == shape, (label, dec.dataset.shape)
    assert dec.dataset.typecode == "e" and dec.dataset.element_size == 2, label
    assert dec.raw == want, f"{label}: decoded bytes differ"
    assert dec.root_links == ["dataset"], label
    print(f"ok   {label}: shape={shape} chunk={chunk} chunks={dec.chunk_count}")


def expect_fail(label: str, words, shape, chunk, needle: str, **kw) -> None:
    data = make_file(words, shape, chunk, **kw)
    try:
        hypersim_h5.decode_file(data)
    except hypersim_h5.H5Error as exc:
        assert needle in str(exc), f"{label}: unexpected error {exc}"
        print(f"ok   {label}: rejected ({exc})")
        return
    raise AssertionError(f"{label}: malformed file was accepted")


def zip_selftest(rng: random.Random) -> None:
    # (a) small stored archive, (b) >65535 entries -> zip64 EOCD record + locator
    for label, n_extra in (("plain zip", 10), ("zip64 EOCD zip", 65600)):
        bio = io.BytesIO()
        members = {}
        with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_STORED) as zf:
            for i in range(n_extra):
                zf.writestr(f"s/pad/{i:06d}.txt", b"x")
            for name in ("s/images/scene_cam_00_geometry_hdf5/frame.0050.normal_cam.hdf5",
                         "s/images/scene_cam_00_geometry_hdf5/frame.0050.normal_world.hdf5"):
                payload = bytes(rng.randrange(256) for _ in range(5000))
                members[name] = payload
                zf.writestr(name, payload)
        blob = bio.getvalue()
        size = len(blob)
        tail_start = max(0, size - 131072)
        cd_off, cd_size, n = hypersim_zip.parse_eocd(blob[tail_start:], tail_start, size)
        assert n == n_extra + 2, (label, n)
        if n_extra > 65535:
            assert b"PK\x06\x06" in blob[tail_start:], "zip64 EOCD expected"
        cd = blob[cd_off:cd_off + cd_size]
        for name, payload in members.items():
            off, csize, crc, nlen = hypersim_zip.find_member(cd, name)
            slab = blob[off:off + 30 + nlen + 1024 + csize]
            assert hypersim_zip.extract(slab, name, csize, crc) == payload, label
            other = [m for m in members if m != name][0]
            try:
                hypersim_zip.extract(slab, other, csize, crc)
                raise AssertionError("renamed local header accepted")
            except hypersim_zip.ZipError:
                pass
            bad = bytearray(slab)
            bad[30 + nlen + 7] ^= 0xFF
            try:
                hypersim_zip.extract(bytes(bad), name, csize, crc)
                raise AssertionError("corrupted member accepted")
            except hypersim_zip.ZipError:
                pass
        try:
            hypersim_zip.parse_eocd(blob[tail_start:-1], tail_start, size)
            raise AssertionError("truncated tail accepted")
        except hypersim_zip.ZipError:
            pass
        print(f"ok   {label}: {n} entries, members recovered byte-exactly, bad slabs rejected")
    # (c) central directory entry whose offset lives in a zip64 extra field
    name = b"big/member.hdf5"
    extra = struct.pack("<HHQ", 0x0001, 8, 9_000_000_123)
    entry = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 45, 45, 0, 0, 0, 0, 0x1234ABCD, 777, 777,
                        len(name), len(extra), 0, 0, 0, 0, 0xFFFFFFFF) + name + extra
    assert hypersim_zip.find_member(entry, name.decode()) == (9_000_000_123, 777, 0x1234ABCD, len(name))
    print("ok   zip64 extra-field offset resolved")


def main() -> int:
    rng = random.Random(20261008)
    shape = (96, 128, 3)
    words = random_words(rng, 96 * 128 * 3)
    expect_ok("hypersim-like layout (exact chunks)", words, shape, (24, 32, 1))
    expect_ok("edge chunks in every dim", words, shape, (25, 30, 2))
    expect_ok("whole-pixel chunks", words, shape, (40, 50, 3))
    expect_ok("multi-level chunk btree", words, shape, (8, 16, 1), fanout=4)
    expect_ok("continuation message", words, shape, (24, 32, 1), continuation=True)
    expect_ok("shuffle+deflate", words, shape, (24, 32, 1), filters="shuffle+deflate")
    expect_ok("filter mask raw chunk", words, shape, (24, 32, 1), raw_first_chunk=True)
    expect_ok("unfiltered chunks", words, shape, (50, 70, 3), filters="")
    expect_ok("single chunk bigger than dataset", words, shape, (128, 256, 4))
    expect_fail("fletcher32 rejected", words, shape, (24, 32, 1), "unsupported HDF5 filter id 3", extra_filter=3)
    expect_fail("big-endian rejected", words, shape, (24, 32, 1), "not little-endian", big_endian=True)
    expect_fail("integer type rejected", words, shape, (24, 32, 1), "not IEEE floating point", integer=True)
    expect_fail("missing chunk rejected", words, shape, (24, 32, 1), "chunk grid mismatch", drop_chunk=True)
    expect_fail("wrong dataset name rejected", words, shape, (24, 32, 1), "lacks 'dataset'", name="other")
    zip_selftest(rng)
    print("selftest passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
