#!/usr/bin/env python3
"""Synthetic self-test for the STOFS fort.61 decode path (stofs61.py + h5lite.py).

Builds small NetCDF4/HDF5 files shaped like stofs_2d_glo_fcst.61.nc from
scratch: superblock v0, a version-2 root object header with compact links and
an OCHK continuation, global/variable attributes, a (time, station) float64
``zeta`` dataset chunked (1, station) with shuffle(8)+deflate and a two-level
version-1 chunk B-tree whose leaves carry sibling pointers, an unfiltered
chunked ``time`` axis, and contiguous ``x``/``y``/``station_name``.  It then
checks that both chunk routes (recursive descent and leaf sibling chain)
return exactly the original doubles, and that corrupted or out-of-scope
variants and degenerate value matrices are rejected.
"""
from __future__ import annotations

import hashlib
import math
import struct
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
import stofs61 as so  # noqa: E402
from h5lite import UNDEF, lookup3  # noqa: E402

I32 = bytes.fromhex("100800000400000000002000")
U8 = bytes.fromhex("100000000100000000000800")
N_TIME, N_STATION, TIME_CHUNK, NAME_LEN = 37, 11, 16, 6
DATE = "2024-06-01"


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


def message(mtype: int, payload: bytes, with_order: bool) -> bytes:
    return struct.pack("<BHB", mtype, len(payload), 0) + (b"\x00\x00" if with_order else b"") + payload


def ohdr(messages: list[tuple[int, bytes]], flags: int) -> bytes:
    with_order = bool(flags & 0x04)
    body = b"".join(message(t, p, with_order) for t, p in messages)
    size_len = 1 << (flags & 0x03)
    return checksummed(b"OHDR" + bytes([2, flags]) + len(body).to_bytes(size_len, "little") + body)


def attribute(name: str, datatype: bytes, dims: tuple[int, ...], data: bytes) -> bytes:
    raw_name = name.encode() + b"\x00"
    space = dataspace(dims)
    return bytes([3, 0]) + struct.pack("<HHH", len(raw_name), len(datatype), len(space)) + b"\x00" + raw_name + datatype + space + data


def attr_value(name: str, value) -> bytes:
    if isinstance(value, str):
        raw = value.encode()
        return attribute(name, fixed_string_type(len(raw)), (), raw)
    if all(isinstance(v, float) for v in value):
        return attribute(name, so.F64_LE, (len(value),), struct.pack(f"<{len(value)}d", *value))
    return attribute(name, I32, (len(value),), struct.pack(f"<{len(value)}i", *value))


def link_message(name: str, target: int) -> bytes:
    raw = name.encode()
    return bytes([1, 0x00, len(raw)]) + raw + struct.pack("<Q", target)


def filters_v2(entries: list[tuple[int, tuple[int, ...]]]) -> bytes:
    out = bytes([2, len(entries)])
    for fid, values in entries:
        out += struct.pack("<HHH", fid, 1, len(values)) + struct.pack(f"<{len(values)}I", *values)
    return out


def filters_v1(entries: list[tuple[int, tuple[int, ...]]]) -> bytes:
    out = bytes([1, len(entries)]) + b"\x00" * 6
    for fid, values in entries:
        out += struct.pack("<4H", fid, 0, 1, len(values)) + struct.pack(f"<{len(values)}I", *values)
        if len(values) % 2:
            out += b"\x00" * 4
    return out


def naive_shuffle(values: bytes, size: int = 8) -> bytes:
    count = len(values) // size
    out = bytearray(len(values))
    for k in range(count):
        for j in range(size):
            out[j * count + k] = values[k * size + j]
    return bytes(out)


def synthetic_matrix(n_time: int = N_TIME, n_station: int = N_STATION) -> list[float]:
    values = []
    for t in range(n_time):
        for s in range(n_station):
            if s == 3:
                v = so.FILL  # a permanently dry station
            elif s == 7 and t % 5 == 0:
                v = so.FILL  # an intermittently wetting/drying station
            elif s == 9:
                v = 118.0 + 0.37 * math.sin(t / 7.0)  # far above the geoid, like real station 1649
            else:
                v = 1.7 * math.sin(2 * math.pi * t / 12.42 + s) + 0.01 * s - 0.3 * math.cos(t / 3.1 + s * s)
            values.append(v)
    return values


def synthetic_names(variant: str) -> bytes:
    out = b""
    for s in range(N_STATION):
        label = (f"S{s:02d}" + ("x" if variant == "after" and s == 5 else "")).encode()
        out += label + b"\x00" * (NAME_LEN - len(label))
    return out


def synthetic_xy() -> tuple[bytes, bytes]:
    x = struct.pack(f"<{N_STATION}d", *[-70.0 + 1.25 * s for s in range(N_STATION)])
    y = struct.pack(f"<{N_STATION}d", *[40.0 - 0.5 * s for s in range(N_STATION)])
    return x, y


def synthetic_spec() -> dict:
    x, y = synthetic_xy()
    return {
        "n_time": N_TIME,
        "n_station": N_STATION,
        "time_chunk": TIME_CHUNK,
        "name_len": NAME_LEN,
        "xy_sha256": hashlib.sha256(x + y).hexdigest(),
        "names_sha256_before": hashlib.sha256(synthetic_names("before")).hexdigest(),
        "names_sha256_after": hashlib.sha256(synthetic_names("after")).hexdigest(),
        "names_switch_date": "2025-03-08",
        "min_distinct": 300,
        "globals": dict(so.REAL_SPEC["globals"]),
    }


def build(values: list[float], *, date: str = DATE, filters: list | None = None, pipeline_v1: bool = False,
          drop_chunk: bool = False, mask_chunk: int | None = None, stored_cut: int = 0,
          break_sibling: bool = False, perturb_x: bool = False, names: str = "before",
          time_shift: float = 0.0, extra_link: bool = False, version: str | None = None) -> bytes:
    if filters is None:
        filters = [(2, (8,)), (1, (2,))]
    w = Writer()
    sb = w.alloc(96)
    base = so.cycle_seconds(date)

    # zeta chunks (shuffle + deflate), each its own deflate stream
    chunk_entries = []
    for t in range(N_TIME):
        row = struct.pack(f"<{N_STATION}d", *values[t * N_STATION:(t + 1) * N_STATION])
        stored = zlib.compress(naive_shuffle(row), 2)
        if stored_cut and t == N_TIME // 2:
            stored = stored[:-stored_cut]
        mask = 1 if mask_chunk == t else 0
        chunk_entries.append((len(stored), mask, (t, 0, 0), w.add(stored)))
    if drop_chunk:
        chunk_entries.pop()
    # two-level v1 B-tree: leaves of <= 5 entries, linked by sibling pointers
    leaves = [chunk_entries[i:i + 5] for i in range(0, len(chunk_entries), 5)]
    leaf_addrs = [w.alloc(24 + 5 * 40 + 32) for _ in leaves]

    def key(size: int, mask: int, offsets: tuple[int, ...]) -> bytes:
        return struct.pack("<II3Q", size, mask, *offsets)

    for i, entries in enumerate(leaves):
        left = leaf_addrs[i - 1] if i else UNDEF
        right = leaf_addrs[i + 1] if i + 1 < len(leaves) else UNDEF
        if break_sibling and i == 2:
            right = UNDEF
        body = b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", len(entries), left, right)
        for size, mask, offsets, addr in entries:
            body += key(size, mask, offsets) + struct.pack("<Q", addr)
        body += key(0, 0, (entries[-1][2][0], N_STATION, 8))
        w.put(leaf_addrs[i], body)
    root_body = b"TREE" + bytes([1, 1]) + struct.pack("<HQQ", len(leaves), UNDEF, UNDEF)
    for entries, addr in zip(leaves, leaf_addrs):
        root_body += key(0, 0, entries[0][2]) + struct.pack("<Q", addr)
    root_body += key(0, 0, (N_TIME - 1, N_STATION, 8))
    zeta_tree = w.add(root_body)
    pipeline = filters_v1(filters) if pipeline_v1 else filters_v2(filters)
    zeta_attrs = [attr_value(k, v) for k, v in so.ZETA_ATTRS.items()]
    zeta = w.add(ohdr(
        [(0x01, dataspace((N_TIME, N_STATION))), (0x03, so.F64_LE), (0x0B, pipeline),
         (0x08, bytes([3, 2, 3]) + struct.pack("<Q", zeta_tree) + struct.pack("<3I", 1, N_STATION, 8))]
        + [(0x0C, a) for a in zeta_attrs],
        0x02,
    ))

    # time: unfiltered chunks of TIME_CHUNK doubles
    times = [float(base - so.NOWCAST_S + so.TIME_STEP_S * (i + 1)) + time_shift for i in range(N_TIME)]
    n_tchunks = -(-N_TIME // TIME_CHUNK)
    padded = times + [0.0] * (n_tchunks * TIME_CHUNK - N_TIME)
    tentries = []
    for k in range(n_tchunks):
        data = struct.pack(f"<{TIME_CHUNK}d", *padded[k * TIME_CHUNK:(k + 1) * TIME_CHUNK])
        tentries.append((len(data), w.add(data), k * TIME_CHUNK))
    tbody = b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", len(tentries), UNDEF, UNDEF)
    for size, addr, offset in tentries:
        tbody += struct.pack("<II2Q", size, 0, offset, 0) + struct.pack("<Q", addr)
    tbody += struct.pack("<II2Q", 0, 0, n_tchunks * TIME_CHUNK, 8)
    time_tree = w.add(tbody)
    time_obj = w.add(ohdr(
        [(0x01, dataspace((N_TIME,))), (0x03, so.F64_LE),
         (0x08, bytes([3, 2, 2]) + struct.pack("<Q", time_tree) + struct.pack("<2I", TIME_CHUNK, 8)),
         (0x0C, attr_value("units", "seconds since 2024-04-04 12:00:00        ! NCDASE - BASE_DAT"))],
        0x02,
    ))

    def contiguous(dims: tuple[int, ...], datatype: bytes, data: bytes | None) -> int:
        if data is None:
            layout = bytes([3, 1]) + struct.pack("<QQ", UNDEF, 0)
        else:
            layout = bytes([3, 1]) + struct.pack("<QQ", w.add(data), len(data))
        return w.add(ohdr([(0x01, dataspace(dims)), (0x03, datatype), (0x08, layout)], 0x02))

    x, y = synthetic_xy()
    if perturb_x:
        x = x[:-1] + bytes([x[-1] ^ 0x01])
    targets = {
        "time": time_obj,
        "station": contiguous((N_STATION,), so.F64_LE, None),
        "namelen": contiguous((NAME_LEN,), so.F64_LE, None),
        "station_name": contiguous((N_STATION, NAME_LEN), U8, synthetic_names(names)),
        "x": contiguous((N_STATION,), so.F64_LE, x),
        "y": contiguous((N_STATION,), so.F64_LE, y),
        "zeta": zeta,
    }
    if extra_link:
        targets["zeta_decoy"] = zeta

    globals_ = dict(so.REAL_SPEC["globals"])
    if version is not None:
        globals_["version"] = version
    globals_["rundes"] = f"{date.replace('-', '')}00 :-6 hr nowcast and +180 hr forecast ! 32 CHARACTER ALPHANUMERIC RUN D"
    globals_["rnday"] = [base / 86400.0]
    globals_["creation_date"] = "selftest"
    items = [attr_value(k, v) for k, v in globals_.items()]
    first, rest = items[: len(items) // 2], items[len(items) // 2:]
    ochk_body = b"OCHK" + b"".join(message(0x0C, p, True) for p in rest)
    ochk = w.add(checksummed(ochk_body))
    link_info = bytes([0, 0x00]) + struct.pack("<QQ", UNDEF, UNDEF)
    root_msgs = [(0x02, link_info), (0x0A, b"\x00\x00")]
    root_msgs += [(0x06, link_message(name, addr)) for name, addr in targets.items()]
    root_msgs += [(0x0C, p) for p in first]
    root_msgs.append((0x10, struct.pack("<QQ", ochk, len(ochk_body) + 4)))
    root = w.add(ohdr(root_msgs, 0x0D))
    eof = len(w.buf)
    w.put(
        sb,
        b"\x89HDF\r\n\x1a\n" + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
        + struct.pack("<4Q", 0, UNDEF, eof, UNDEF) + struct.pack("<QQII", 0, root, 0, 0) + b"\x00" * 16,
    )
    return bytes(w.buf)


def decode_sample(raw: bytes, spec: dict, route: str, date: str = DATE) -> tuple[bytes, list[bytes]]:
    payloads, _meta = so.decode_cycle(raw, date, spec, route)
    return b"".join(so.unshuffle(p, spec["n_station"]) for p in payloads), payloads


def expect_failure(label: str, func) -> None:
    try:
        func()
    except so.DECODE_ERRORS:
        return
    raise SystemExit(f"selftest: {label} was not rejected")


def main(quiet: bool = False) -> None:
    # lookup3 reference vectors (Bob Jenkins' lookup3.c driver5()).
    assert lookup3(b"") == 0xDEADBEEF
    assert lookup3(b"Four score and seven years ago") == 0x17770551

    # shuffle helpers against the byte-loop reference definition
    sample_bytes = bytes((i * 37 + (i >> 3) * 11) & 0xFF for i in range(8 * 29))
    if so.shuffle(sample_bytes) != naive_shuffle(sample_bytes):
        raise SystemExit("selftest: shuffle differs from reference")
    if so.unshuffle(naive_shuffle(sample_bytes), 29) != sample_bytes:
        raise SystemExit("selftest: unshuffle does not invert the reference shuffle")

    # S3 multipart ETag helper
    blob = bytes(range(256)) * 10
    manual = hashlib.md5(b"".join(hashlib.md5(blob[i:i + 1000]).digest() for i in (0, 1000, 2000))).hexdigest() + "-3"
    if so.s3_multipart_etag(blob, 3, 1000) != manual or so.s3_multipart_etag(blob, 2, 1000) == manual:
        raise SystemExit("selftest: multipart ETag helper is wrong")

    spec = synthetic_spec()
    values = synthetic_matrix()
    expected = struct.pack(f"<{len(values)}d", *values)
    for pipeline_v1 in (False, True):
        raw = build(values, pipeline_v1=pipeline_v1)
        for route in ("descent", "siblings"):
            sample, payloads = decode_sample(raw, spec, route)
            if sample != expected:
                raise SystemExit(f"selftest: decoded matrix differs (route {route}, v1 pipeline {pipeline_v1})")
            for t, payload in enumerate(payloads):
                row = sample[t * N_STATION * 8:(t + 1) * N_STATION * 8]
                if so.shuffle(row) != payload:
                    raise SystemExit("selftest: verify re-shuffle does not reproduce the chunk")
    profile = so.sample_profile(expected, spec)
    fills = sum(1 for v in values if v == so.FILL)
    if (profile["fill_count"], profile["stations_with_fill"], profile["always_fill_stations"]) != (fills, 2, 1):
        raise SystemExit(f"selftest: fill accounting wrong: {profile}")
    nonfill = [v for v in values if v != so.FILL]
    if profile["min"] != min(nonfill) or profile["max"] != max(nonfill):
        raise SystemExit("selftest: min/max must exclude the fill value")

    good = build(values)
    expect_failure("wrong cycle date", lambda: so.decode_cycle(good, "2024-06-21", spec, "descent"))
    expect_failure("shuffle element size 4", lambda: decode_sample(build(values, filters=[(2, (4,)), (1, (2,))]), spec, "descent"))
    expect_failure("deflate-only pipeline", lambda: decode_sample(build(values, filters=[(1, (2,))]), spec, "descent"))
    expect_failure("extra fletcher32 filter", lambda: decode_sample(build(values, filters=[(2, (8,)), (1, (2,)), (3, ())]), spec, "descent"))
    expect_failure("missing chunk", lambda: decode_sample(build(values, drop_chunk=True), spec, "descent"))
    expect_failure("filter mask set", lambda: decode_sample(build(values, mask_chunk=4), spec, "siblings"))
    expect_failure("truncated chunk", lambda: decode_sample(build(values, stored_cut=5), spec, "descent"))
    broken = build(values, break_sibling=True)
    if decode_sample(broken, spec, "descent")[0] != expected:
        raise SystemExit("selftest: descent route should ignore leaf sibling pointers")
    expect_failure("broken leaf sibling chain", lambda: decode_sample(broken, spec, "siblings"))
    expect_failure("moved station", lambda: decode_sample(build(values, perturb_x=True), spec, "descent"))
    expect_failure("renamed station before switch date", lambda: decode_sample(build(values, names="after"), spec, "descent"))
    late = build(values, date="2025-06-16", names="after")
    if decode_sample(late, spec, "siblings", "2025-06-16")[0] != expected:
        raise SystemExit("selftest: post-switch station names should decode")
    expect_failure("old names after switch date", lambda: decode_sample(build(values, date="2025-06-16"), spec, "descent", "2025-06-16"))
    expect_failure("shifted time axis", lambda: decode_sample(build(values, time_shift=360.0), spec, "descent"))
    expect_failure("extra root link", lambda: decode_sample(build(values, extra_link=True), spec, "descent"))
    expect_failure("other model version", lambda: decode_sample(build(values, version="noaa.stofs.2d.glo.v3.1.0"), spec, "descent"))
    corrupt = bytearray(good)
    pos = corrupt.find(b"OHDR") + 16  # inside the checksummed message area
    corrupt[pos] ^= 0x40
    expect_failure("corrupted object header checksum", lambda: decode_sample(bytes(corrupt), spec, "descent"))

    def with_value(index: int, value: float) -> bytes:
        changed = list(values)
        changed[index] = value
        return struct.pack(f"<{len(changed)}d", *changed)

    expect_failure("NaN value", lambda: so.sample_profile(with_value(5, float("nan")), spec))
    expect_failure("infinite value", lambda: so.sample_profile(with_value(5, float("inf")), spec))
    expect_failure("out-of-range value", lambda: so.sample_profile(with_value(5, 600.0), spec))
    expect_failure("all-fill sample", lambda: so.sample_profile(struct.pack("<d", so.FILL) * len(values), spec))
    expect_failure("constant sample", lambda: so.sample_profile(struct.pack("<d", 0.5) * len(values), spec))
    if not quiet:
        print("selftest=ok synthetic fort.61 decode, routes, rejection and profile checks passed")


if __name__ == "__main__":
    main()
