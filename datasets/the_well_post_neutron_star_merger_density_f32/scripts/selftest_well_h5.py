#!/usr/bin/env python3
"""Self-test for well_h5.py and the well_density.py validators.

Writes a tiny synthetic HDF5 file by hand with the same structure the pinned
files use (superblock v2 + lookup3 checksum, v1 object headers, symbol-table
groups, contiguous F32LE datasets, float64 root attributes), then checks that
the layout validator accepts it and rejects targeted corruptions. Also checks
lookup3 against the reference vectors from lookup3.c and exercises the
snapshot and HTTP-header validators. Uses no network and no local data.
"""

from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import well_density as wd  # noqa: E402
from well_h5 import H5T_IEEE_F32LE, H5T_IEEE_F64LE, UNDEF, lookup3  # noqa: E402

GRID = (4, 3, 6)
NT = 5
DIMS_START = 4096
DENSITY_ADDRESS = 8192


def pad8(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 8)


def message(mtype: int, payload: bytes, flags: int = 0) -> bytes:
    payload = pad8(payload)
    return struct.pack("<HHB3x", mtype, len(payload), flags) + payload


def object_header(messages: list[bytes]) -> bytes:
    body = b"".join(messages)
    return struct.pack("<BBHII4x", 1, 0, len(messages), 1, len(body)) + body


def dataspace(dims: tuple[int, ...]) -> bytes:
    return struct.pack("<BBB5x", 1, len(dims), 0) + b"".join(struct.pack("<Q", d) for d in dims)


def layout_contiguous(address: int, size: int) -> bytes:
    return struct.pack("<BBQQ", 3, 1, address, size)


def attribute_f64(name: str, value: float) -> bytes:
    raw_name = name.encode() + b"\0"
    space = struct.pack("<BBB5x", 1, 0, 0)
    return (struct.pack("<BBHHH", 1, 0, len(raw_name), len(H5T_IEEE_F64LE), len(space))
            + pad8(raw_name) + pad8(H5T_IEEE_F64LE) + pad8(space) + struct.pack("<d", value))


class Writer:
    def __init__(self, size: int):
        self.buf = bytearray(size)
        self.cursor = 64  # after the superblock

    def alloc(self, data: bytes) -> int:
        address = self.cursor
        self.buf[address : address + len(data)] = data
        self.cursor = (address + len(data) + 7) & ~7
        if self.cursor > DIMS_START:
            raise RuntimeError("synthetic metadata overflow")
        return address

    def group(self, children: dict[str, int], extra: list[bytes] | None = None) -> int:
        names = sorted(children)
        heap_data = b"\0" * 8
        offsets = {}
        for name in names:
            offsets[name] = len(heap_data)
            heap_data += pad8(name.encode() + b"\0")
        heap_data_addr = self.alloc(heap_data)
        heap = self.alloc(b"HEAP" + bytes([0, 0, 0, 0]) + struct.pack("<QQQ", len(heap_data), UNDEF, heap_data_addr))
        snod = b"SNOD" + bytes([1, 0]) + struct.pack("<H", len(names))
        for name in names:
            snod += struct.pack("<QQII16x", offsets[name], children[name], 0, 0)
        snod_addr = self.alloc(snod)
        tree = b"TREE" + bytes([0, 0]) + struct.pack("<HQQ", 1, UNDEF, UNDEF)
        tree += struct.pack("<QQQ", 0, snod_addr, offsets[names[-1]])
        tree_addr = self.alloc(tree)
        msgs = [message(0x0011, struct.pack("<QQ", tree_addr, heap))] + (extra or [])
        return self.alloc(object_header(msgs))

    def dataset(self, dims: tuple[int, ...], address: int, size: int, dtype: bytes = H5T_IEEE_F32LE,
                extra: list[bytes] | None = None, layout: bytes | None = None) -> int:
        msgs = [message(0x0001, dataspace(dims)), message(0x0003, dtype),
                message(0x0008, layout or layout_contiguous(address, size))] + (extra or [])
        return self.alloc(object_header(msgs))



def synthetic(corrupt: str = "") -> tuple[bytes, dict]:
    nr, nth, nph = GRID
    snap = nr * nth * nph
    density_size = NT * snap * 4
    file_size = DENSITY_ADDRESS + density_size
    w = Writer(file_size)
    # dims block: time, log_r, theta, phi, a, mbh (contiguous F32LE)
    time = [500.0 + 50.0 * i for i in range(NT)]
    if corrupt == "time_order":
        time[2] = time[1]
    log_r = [0.3 + 0.5 * i for i in range(nr)]
    theta = [i / (nth - 1) for i in range(nth)]
    phi = [2 * math.pi * i / (nph - 1) for i in range(nph)]
    blobs = {}
    cursor = DIMS_START
    for name, values in (("time", time), ("log_r", log_r), ("theta", theta), ("phi", phi),
                         ("a", [0.8]), ("mbh", [5.967e33])):
        raw = struct.pack(f"<{len(values)}f", *values)
        w.buf[cursor : cursor + len(raw)] = raw
        blobs[name] = (cursor, len(raw), len(values))
        cursor += len(raw)
    dims_end = cursor - 1
    # density: value = smooth positive field, distinct per cell
    values = []
    for t in range(NT):
        for i in range(snap):
            values.append(1e-8 + (i + 1) * 1.0e-3 * (1 + t))
    w.buf[DENSITY_ADDRESS : DENSITY_ADDRESS + density_size] = struct.pack(f"<{len(values)}f", *values)

    dens_extra, dens_dtype, dens_layout, dens_addr = [], H5T_IEEE_F32LE, None, DENSITY_ADDRESS
    if corrupt == "filter":
        dens_extra = [message(0x000B, struct.pack("<BB6xHHHH", 1, 1, 1, 0, 0, 1) + struct.pack("<I4x", 4))]
    if corrupt == "dtype":
        dens_dtype = H5T_IEEE_F64LE
    if corrupt == "chunked":
        dens_layout = struct.pack("<BBBQ", 3, 2, 6, UNDEF) + struct.pack("<6I", 1, 1, nr, nth, nph, 4)
    if corrupt == "address":
        dens_addr = DENSITY_ADDRESS + 8
    density = w.dataset((1, NT, nr, nth, nph), dens_addr, density_size, dens_dtype, dens_extra, dens_layout)
    ds = {name: w.dataset((count,) if name not in ("a", "mbh") else (), addr, size)
          for name, (addr, size, count) in blobs.items()}
    t0 = w.group({"density": density})
    dims_group = w.group({k: ds[k] for k in ("time", "log_r", "theta", "phi")})
    scalars = w.group({k: ds[k] for k in ("a", "mbh")})
    root = w.group({"t0_fields": t0, "dimensions": dims_group, "scalars": scalars},
                   extra=[message(0x000C, attribute_f64("a", 0.8)), message(0x000C, attribute_f64("mbh", 3.0))])
    sb = b"\x89HDF\r\n\x1a\n" + bytes([2, 8, 8, 0]) + struct.pack("<QQQQ", 0, UNDEF, file_size, root)
    checksum = lookup3(sb)
    if corrupt == "checksum":
        checksum ^= 1
    w.buf[0:48] = sb + struct.pack("<I", checksum)
    expected = {
        "file_size": file_size,
        "head_range": (0, DIMS_START - 1),
        "dims_range": (DIMS_START, dims_end),
        "density_path": "/t0_fields/density",
        "density_shape": (1, NT, nr, nth, nph),
        "density_address": DENSITY_ADDRESS,
        "grid": GRID,
        "n_time": NT,
    }
    return bytes(w.buf), expected


def run_layout(data: bytes, expected: dict) -> dict:
    h0, h1 = expected["head_range"]
    d0, d1 = expected["dims_range"]
    return wd.inspect_head(data[h0 : h1 + 1], data[d0 : d1 + 1], expected)


def expect_fail(label: str, fn) -> None:
    try:
        fn()
    except (wd.RecipeError, ValueError) as exc:
        print(f"ok   rejects {label}: {str(exc)[:90]}")
        return
    raise SystemExit(f"FAIL: {label} was accepted")


def main() -> None:
    # lookup3 reference vectors (lookup3.c driver5).
    assert lookup3(b"") == 0xDEADBEEF, hex(lookup3(b""))
    assert lookup3(b"Four score and seven years ago") == 0x17770551
    assert lookup3(b"Four score and seven years ago", 1) == 0xCD628161
    print("ok   lookup3 reference vectors")

    data, expected = synthetic()
    layout = run_layout(data, expected)
    nr, nth, nph = GRID
    assert layout["density_address"] == DENSITY_ADDRESS and layout["density_shape"] == [1, NT, nr, nth, nph]
    assert len(layout["time"]) == NT and layout["time"][0] == 500.0
    assert layout["bh_spin_a"] == 0.8 and layout["bh_mass_msun"] == 3.0
    snap_bytes = nr * nth * nph * 4
    off = layout["density_address"] + 3 * snap_bytes
    values = struct.unpack(f"<{nr * nth * nph}f", data[off : off + snap_bytes])
    assert abs(values[0] - (1e-8 + 1e-3 * 4)) < 1e-9 and abs(values[-1] - (1e-8 + nr * nth * nph * 1e-3 * 4)) < 1e-4
    print(f"ok   synthetic layout parsed: {layout['density_address']}+{layout['density_size']} times={len(layout['time'])}")

    for corrupt in ("checksum", "filter", "dtype", "chunked", "address", "time_order"):
        bad, exp = synthetic(corrupt)
        expect_fail(corrupt, lambda: run_layout(bad, exp))
    expect_fail("truncated head", lambda: wd.inspect_head(data[:100], data[expected["dims_range"][0]:expected["dims_range"][1] + 1], expected))

    # snapshot statistics on a (4, 3, 6) grid
    good = struct.pack("<72f", *[1e-8 * (1.5 ** i) for i in range(72)])
    stats = wd.snapshot_stats(good, GRID)
    assert stats["distinct_values"] == 72 and stats["phi_constant_rows"] == 0 and stats["zero_values"] == 0
    assert stats["min"] == struct.unpack("<f", struct.pack("<f", 1e-8))[0]
    assert stats["max"] == struct.unpack("<f", struct.pack("<f", 1e-8 * 1.5 ** 71))[0]
    rows = struct.pack("<72f", *[float(1 + i // 6) for i in range(72)])
    assert wd.snapshot_stats(rows, GRID)["phi_constant_rows"] == 12
    print("ok   snapshot statistics (min/max from stored float32, phi-constant rows)")
    for label, vals in (("nan", [float("nan")] + [1.0] * 71), ("inf", [float("inf")] + [1.0] * 71),
                        ("negative", [-1.0] + [1.0] * 71), ("negative zero", [-0.0] + [1.0] * 71)):
        raw = struct.pack("<72f", *vals)
        expect_fail(label, lambda raw=raw: wd.snapshot_stats(raw, GRID))
    expect_fail("constant snapshot", lambda: wd.check_stats(wd.snapshot_stats(struct.pack("<72f", *[2.0] * 72), GRID)))
    expect_fail("short snapshot", lambda: wd.snapshot_stats(good[:-4], GRID))

    # HTTP header dumps
    ident = "e5068c957fd2f3fe83fd82ee9a05b7c5f6d76ea8f6391bd8b42c92ef37142c3c"
    lfs = "bf59d08b358bc21638b876a192259c37e6002b9f08187d592abe6503ebf7579e"
    ok = (f"HTTP/1.1 200 Connection established\r\n\r\nHTTP/2 302\r\nx-linked-etag: \"{lfs}\"\r\n"
          f"x-xet-hash: {ident}\r\nlocation: https://cdn/x\r\n\r\n"
          f"HTTP/1.1 200 Connection established\r\n\r\nHTTP/2 206\r\netag: \"{ident}\"\r\n"
          f"content-range: bytes 100-199/1000\r\n\r\n")
    wd.check_headers(ok, 100, 199, 1000, {ident, lfs})
    print("ok   accepts proxied 302 -> 206 header chain")
    expect_fail("HTTP 200", lambda: wd.check_headers(ok.replace("HTTP/2 206", "HTTP/2 200"), 100, 199, 1000, {ident}))
    expect_fail("wrong range", lambda: wd.check_headers(ok, 100, 198, 1000, {ident}))
    expect_fail("wrong total", lambda: wd.check_headers(ok, 100, 199, 999, {ident}))
    expect_fail("wrong identity", lambda: wd.check_headers(ok, 100, 199, 1000, {"0" * 64}))
    print("selftest passed")


if __name__ == "__main__":
    main()
