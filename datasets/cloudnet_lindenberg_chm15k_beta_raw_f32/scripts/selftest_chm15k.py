#!/usr/bin/env python3
"""Synthetic self-test for the Cloudnet CHM15k beta_raw decode path.

Builds small NetCDF4/HDF5 files shaped like a cloudnetpy lidar product from
scratch: superblock v2 (lookup3-checksummed), version-2 object headers with
compact links and attributes, a (time, range) float32 ``beta_raw`` dataset
chunked (16, 10) over a (37, 23) array, so 3 x 3 chunks including padded edge
chunks, filtered [shuffle(4), deflate] and indexed by a two-level version-1
B-tree whose leaves carry sibling pointers, plus multi-chunk ``time`` and
single-chunk ``range`` axes.  It checks that both decode routes (recursive
descent + slice unshuffle, sibling chain + streamed inflate + lane-zip
unshuffle) return exactly the original float32 bytes, that lookup3 matches
published vectors, and that corrupted, out-of-scope or degenerate variants are
rejected.
"""
from __future__ import annotations

import os
import random
import struct
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chm15k as ck  # noqa: E402
from h5lite import UNDEF, lookup3  # noqa: E402

N_TIME, N_RANGE = 37, 23
CHUNK = (16, 10)
TIME_CHUNK = 16
DATE = "2024-06-01"
UUID = "00000000-1111-2222-3333-444444444444"
ROW = {"date": DATE, "uuid": UUID, "filename": "x.nc", "size": 0, "sha256": "", "cloudnetpy_version": "1.75.0"}


def spec() -> dict:
    s = dict(ck.REAL_SPEC)
    s.update({"n_range": N_RANGE, "min_time": 30, "max_time": 40, "min_distinct": 400, "distinct_stride": 1})
    return s


def fixed_string_type(size: int) -> bytes:
    return bytes([0x13, 0, 0, 0]) + struct.pack("<I", size)


def dataspace(dims: tuple[int, ...]) -> bytes:
    if not dims:
        return bytes([2, 0, 0, 0])
    return bytes([2, len(dims), 0, 1]) + struct.pack(f"<{len(dims)}Q", *dims)


class Writer:
    def __init__(self) -> None:
        self.buf = bytearray()

    def alloc(self, size: int) -> int:
        while len(self.buf) % 8:
            self.buf.append(0)
        addr = len(self.buf)
        self.buf.extend(b"\x00" * size)
        return addr

    def put(self, addr: int, data: bytes) -> None:
        self.buf[addr:addr + len(data)] = data

    def add(self, data: bytes) -> int:
        addr = self.alloc(len(data))
        self.put(addr, data)
        return addr


def checksummed(body: bytes) -> bytes:
    return body + struct.pack("<I", lookup3(body))


def ohdr(messages: list[tuple[int, bytes]]) -> bytes:
    body = b"".join(struct.pack("<BHB", t, len(p), 0) + p for t, p in messages)
    flags = 0x02  # 4-byte chunk size field, no times/order
    return checksummed(b"OHDR" + bytes([2, flags]) + struct.pack("<I", len(body)) + body)


def attribute(name: str, datatype: bytes, dims: tuple[int, ...], data: bytes) -> bytes:
    raw_name = name.encode() + b"\x00"
    space = dataspace(dims)
    return bytes([3, 0]) + struct.pack("<HHH", len(raw_name), len(datatype), len(space)) + b"\x00" + raw_name + datatype + space + data


def attr_str(name: str, value: str) -> bytes:
    raw = value.encode()
    return attribute(name, fixed_string_type(len(raw)), (), raw)


def link_message(name: str, target: int) -> bytes:
    raw = name.encode()
    return bytes([1, 0x00, len(raw)]) + raw + struct.pack("<Q", target)


def filters_v2(entries: list[tuple[int, tuple[int, ...]]]) -> bytes:
    out = bytes([2, len(entries)])
    for fid, values in entries:
        out += struct.pack("<HHH", fid, 1, len(values)) + struct.pack(f"<{len(values)}I", *values)
    return out


def naive_shuffle(values: bytes, size: int = 4) -> bytes:
    count = len(values) // size
    out = bytearray(len(values))
    for k in range(count):
        for j in range(size):
            out[j * count + k] = values[k * size + j]
    out[count * size:] = values[count * size:]
    return bytes(out)


def synthetic_beta(kind: str = "normal") -> list[float]:
    rng = random.Random(1535)
    vals = []
    for t in range(N_TIME):
        for g in range(N_RANGE):
            v = rng.gauss(0.0, 1e-5) + (3e-4 if 8 <= g <= 10 and t % 7 < 3 else 0.0)
            vals.append(v)
    if kind == "fill":
        vals[5 * N_RANGE + 4] = ck.FILL_F32
    elif kind == "nan":
        vals[100] = float("nan")
    elif kind == "constant":
        vals = [2.5e-6] * len(vals)
    elif kind == "heavy_fill":
        for i in range(0, 3 * N_RANGE):
            vals[i] = ck.FILL_F32
    return vals


def f32bytes(vals: list[float]) -> bytes:
    return struct.pack(f"<{len(vals)}f", *vals)


def build(beta_vals: list[float], *, filters=None, drop_chunk=False, mask_chunk=None, break_sibling=False,
          datatype=None, file_uuid=UUID, dt_s=15.0, corrupt_ohdr=False, fill_attr=None) -> bytes:
    if filters is None:
        filters = [(2, (4,)), (1, (4,))]
    dtype = datatype or ck.F32_LE
    w = Writer()
    sb = w.alloc(48)
    rng = random.Random(7)

    def chunk_payload(raw_values: bytes) -> bytes:
        data = raw_values
        for fid, _cd in filters:
            if fid == 2:
                data = naive_shuffle(data)
            elif fid == 1:
                data = zlib.compress(data, 4)
        return data

    # beta_raw chunks (padded edge chunks carry random garbage outside the array)
    beta = f32bytes(beta_vals)
    entries = []
    for r0 in range(0, N_TIME, CHUNK[0]):
        for c0 in range(0, N_RANGE, CHUNK[1]):
            block = bytearray(rng.getrandbits(8) for _ in range(CHUNK[0] * CHUNK[1] * 4))
            for r in range(CHUNK[0]):
                for c in range(CHUNK[1]):
                    if r0 + r < N_TIME and c0 + c < N_RANGE:
                        src = ((r0 + r) * N_RANGE + c0 + c) * 4
                        dst = (r * CHUNK[1] + c) * 4
                        block[dst:dst + 4] = beta[src:src + 4]
            stored = chunk_payload(bytes(block))
            mask = 1 if mask_chunk == len(entries) else 0
            entries.append((len(stored), mask, (r0, c0, 0), w.add(stored)))
    if drop_chunk:
        entries.pop(4)

    def key(size: int, mask: int, offsets: tuple[int, ...]) -> bytes:
        return struct.pack(f"<II{len(offsets)}Q", size, mask, *offsets)

    leaves = [entries[i:i + 4] for i in range(0, len(entries), 4)]
    leaf_addrs = [w.alloc(24 + 4 * 40 + 32) for _ in leaves]
    for i, group in enumerate(leaves):
        left = leaf_addrs[i - 1] if i else UNDEF
        right = leaf_addrs[i + 1] if i + 1 < len(leaves) else UNDEF
        if break_sibling and i == 1:
            right = UNDEF
        body = b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", len(group), left, right)
        for size, mask, offsets, addr in group:
            body += key(size, mask, offsets) + struct.pack("<Q", addr)
        body += key(0, 0, (N_TIME, N_RANGE, 4))
        w.put(leaf_addrs[i], body)
    root_body = b"TREE" + bytes([1, 1]) + struct.pack("<HQQ", len(leaves), UNDEF, UNDEF)
    for group, addr in zip(leaves, leaf_addrs):
        root_body += key(0, 0, group[0][2]) + struct.pack("<Q", addr)
    root_body += key(0, 0, (N_TIME, N_RANGE, 4))
    beta_tree = w.add(root_body)
    fv = ck.FILL_F32 if fill_attr is None else fill_attr
    beta_attrs = [attr_str(k, v) for k, v in ck.REAL_SPEC["beta_raw_attrs"].items()]
    beta_attrs.append(attribute("_FillValue", ck.F32_LE, (1,), struct.pack("<f", fv)))
    beta_obj = w.add(ohdr(
        [(0x01, dataspace((N_TIME, N_RANGE))), (0x03, dtype), (0x0B, filters_v2(filters)),
         (0x08, bytes([3, 2, 3]) + struct.pack("<Q", beta_tree) + struct.pack("<3I", CHUNK[0], CHUNK[1], 4))]
        + [(0x0C, a) for a in beta_attrs]
    ))

    def axis(values: list[float], chunk: int, units: str | None) -> int:
        n = len(values)
        nchunks = -(-n // chunk)
        padded = values + [0.0] * (nchunks * chunk - n)
        tentries = []
        for k in range(nchunks):
            stored = chunk_payload(f32bytes(padded[k * chunk:(k + 1) * chunk]))
            tentries.append((len(stored), w.add(stored), k * chunk))
        body = b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", len(tentries), UNDEF, UNDEF)
        for size, addr, off in tentries:
            body += key(size, 0, (off, 0)) + struct.pack("<Q", addr)
        body += key(0, 0, (nchunks * chunk, 4))
        tree = w.add(body)
        msgs = [(0x01, dataspace((n,))), (0x03, ck.F32_LE), (0x0B, filters_v2(filters)),
                (0x08, bytes([3, 2, 2]) + struct.pack("<Q", tree) + struct.pack("<2I", chunk, 4))]
        if units:
            msgs.append((0x0C, attr_str("units", units)))
        return w.add(ohdr(msgs))

    time_obj = axis([(8.0 + dt_s * i) / 3600.0 for i in range(N_TIME)], TIME_CHUNK, f"hours since {DATE} 00:00:00 +00:00")
    range_obj = axis([9.99 * (i + 1) for i in range(N_RANGE)], N_RANGE, "m")

    globals_ = dict(ck.REAL_SPEC["globals"])
    y, m, d = DATE.split("-")
    globals_.update({"file_uuid": file_uuid, "year": y, "month": m, "day": d, "cloudnetpy_version": "1.75.0"})
    link_info = bytes([0, 0x00]) + struct.pack("<QQ", UNDEF, UNDEF)
    root_msgs = [(0x02, link_info)]
    root_msgs += [(0x06, link_message(n, a)) for n, a in (("beta_raw", beta_obj), ("range", range_obj), ("time", time_obj))]
    root_msgs += [(0x0C, attr_str(k, v)) for k, v in globals_.items()]
    root = w.add(ohdr(root_msgs))
    if corrupt_ohdr:
        w.buf[root + 20] ^= 0x01
    eof = len(w.buf)
    head = b"\x89HDF\r\n\x1a\n" + bytes([2, 8, 8, 0]) + struct.pack("<4Q", 0, UNDEF, eof, root)
    w.put(sb, head + struct.pack("<I", lookup3(head)))
    return bytes(w.buf)


def expect_failure(label: str, func) -> None:
    try:
        func()
    except (ck.RecipeError,) + ck.DECODE_ERRORS:
        return
    raise SystemExit(f"selftest: {label} was not rejected")


def main(quiet: bool = False) -> None:
    # lookup3 published vectors (Bob Jenkins' lookup3.c driver5)
    assert lookup3(b"", 0) == 0xDEADBEEF
    assert lookup3(b"Four score and seven years ago", 0) == 0x17770551
    assert lookup3(b"Four score and seven years ago", 1) == 0xCD628161

    rnd = random.Random(3)
    for n in (0, 1, 4, 5, 4097, 40003):
        buf = bytes(rnd.getrandbits(8) for _ in range(n))
        sh = naive_shuffle(buf)
        assert ck.unshuffle_slices(sh) == buf, n
        assert ck.unshuffle_lanes(sh) == buf, n
    comp = zlib.compress(os.urandom(3 << 20), 4)
    assert ck.inflate_streamed(comp) == zlib.decompress(comp)

    sp = spec()
    for kind in ("normal", "fill"):
        vals = synthetic_beta(kind)
        raw = build(vals)
        want = f32bytes(vals)
        for route in ("descent", "siblings"):
            info = ck.decode_file(raw, ROW, sp, route)
            assert info["beta"] == want, (kind, route)
            assert (info["n_time"], info["n_range"]) == (N_TIME, N_RANGE)
            assert info["chunk_dims"] == list(CHUNK)
        stats = ck.sample_stats(want, N_TIME, N_RANGE, sp)
        assert stats["fill_count"] == (1 if kind == "fill" else 0)
        good = [v for v in struct.unpack(f"<{len(vals)}f", want) if abs(v) < 1]
        assert stats["min"] == min(good) and stats["max"] == max(good)

    normal = synthetic_beta()
    expect_failure("OHDR checksum corruption", lambda: ck.decode_file(build(normal, corrupt_ohdr=True), ROW, sp, "descent"))
    expect_failure("deflate-only pipeline", lambda: ck.decode_file(build(normal, filters=[(1, (4,))]), ROW, sp, "descent"))
    expect_failure("missing chunk", lambda: ck.decode_file(build(normal, drop_chunk=True), ROW, sp, "descent"))
    expect_failure("missing chunk (siblings)", lambda: ck.decode_file(build(normal, drop_chunk=True), ROW, sp, "siblings"))
    expect_failure("filter mask", lambda: ck.decode_file(build(normal, mask_chunk=2), ROW, sp, "descent"))
    expect_failure("broken sibling chain", lambda: ck.decode_file(build(normal, break_sibling=True), ROW, sp, "siblings"))
    be = bytearray(ck.F32_LE)
    be[1] |= 0x01
    expect_failure("big-endian datatype", lambda: ck.decode_file(build(normal, datatype=bytes(be)), ROW, sp, "descent"))
    expect_failure("wrong file_uuid", lambda: ck.decode_file(build(normal, file_uuid="other"), ROW, sp, "descent"))
    expect_failure("30 s profiles", lambda: ck.decode_file(build(normal, dt_s=30.0), ROW, sp, "descent"))
    expect_failure("non-default _FillValue", lambda: ck.decode_file(build(normal, fill_attr=-999.0), ROW, sp, "descent"))
    expect_failure("NaN value", lambda: ck.sample_stats(f32bytes(synthetic_beta("nan")), N_TIME, N_RANGE, sp))
    expect_failure("constant sample", lambda: ck.sample_stats(f32bytes(synthetic_beta("constant")), N_TIME, N_RANGE, sp))
    expect_failure("fill-dominated sample", lambda: ck.sample_stats(f32bytes(synthetic_beta("heavy_fill")), N_TIME, N_RANGE, sp))
    if not quiet:
        print("selftest_chm15k: all checks passed")


if __name__ == "__main__":
    main()
