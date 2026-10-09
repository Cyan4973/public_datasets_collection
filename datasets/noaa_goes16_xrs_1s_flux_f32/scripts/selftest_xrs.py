#!/usr/bin/env python3
"""Synthetic self-test for the XRS decode paths (build and verify).

Builds small NetCDF4-like HDF5 files from scratch with the same structures as
the real sci_xrsf-l2-flx1s files: superblock v2, version-2 object headers,
dense root links in a fractal heap indexed by a name v2 B-tree and a
creation-order v2 B-tree, dense root attributes, compact variable attributes,
rank-1 (86400,) float32/float64 variables with a shuffle+deflate v2 filter
pipeline, a version-3 chunked layout and a version-1 chunk B-tree with rank-2
keys.  Checks that both decoders return the exact payload, that the
missing-value accounting and day policy are right, and that corrupted or
out-of-scope variants are rejected.
"""
from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
import verify_xrs  # noqa: E402
import xrs_flux as xf  # noqa: E402
from h5lite import UNDEF, lookup3  # noqa: E402

N = xf.N_SECONDS
F32 = xf.F32_TYPE
F64 = xf.F64_TYPE
F32_BE = bytes([0x11, 0x21]) + F32[2:]
DATE = "2022-06-01"
NAME = "sci_xrsf-l2-flx1s_g16_d20220601_v2-2-1.nc"


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
    body = b"".join(message(t, p, bool(flags & 0x04)) for t, p in messages)
    size_len = 1 << (flags & 0x03)
    return checksummed(b"OHDR" + bytes([2, flags]) + len(body).to_bytes(size_len, "little") + body)


def attribute(name: str, datatype: bytes, dims: tuple[int, ...], data: bytes) -> bytes:
    raw_name = name.encode() + b"\x00"
    space = dataspace(dims)
    return (bytes([3, 0]) + struct.pack("<HHH", len(raw_name), len(datatype), len(space)) + b"\x00"
            + raw_name + datatype + space + data)


def string_attr(name: str, value: str) -> bytes:
    raw = value.encode()
    return attribute(name, fixed_string_type(len(raw)), (), raw)


def heap_header(id_len: int, max_managed: int, start: int, max_direct: int, root: int, n_objects: int) -> bytes:
    fields = [0, UNDEF, 0, UNDEF, 0, 0, 0, n_objects, 0, 0, 0, 0]
    body = (b"FRHP" + bytes([0]) + struct.pack("<HHBI", id_len, 0, 0x02, max_managed)
            + struct.pack("<12Q", *fields) + struct.pack("<HQQHHQH", 4, start, max_direct, 32, 1, root, 0))
    return checksummed(body)


def direct_block(heap_addr: int, size: int, objects: bytes) -> bytes:
    head = b"FHDB" + bytes([0]) + struct.pack("<QI", heap_addr, 0)
    block = bytearray(head + b"\x00\x00\x00\x00" + objects)
    if len(block) > size:
        raise AssertionError("synthetic direct block overflow")
    block.extend(b"\x00" * (size - len(block)))
    block[len(head):len(head) + 4] = struct.pack("<I", lookup3(bytes(block)))
    return bytes(block)


def heap_id(offset: int, length: int, id_len: int) -> bytes:
    out = bytes([0]) + struct.pack("<I", offset) + struct.pack("<H", length)
    return out + b"\x00" * (id_len - len(out))


def bthd(btype: int, record_size: int, root: int, total: int) -> bytes:
    return checksummed(b"BTHD" + bytes([0, btype])
                       + struct.pack("<IHHBBQHQ", 512, record_size, 0, 100, 40, root, total, total))


def btlf(btype: int, records: list[bytes]) -> bytes:
    return checksummed(b"BTLF" + bytes([0, btype]) + b"".join(records))


def shuffle(data: bytes, element: int) -> bytes:
    return b"".join(data[lane::element] for lane in range(element))


def synthetic_flux(scale: float, n_fill: int, seed: int) -> bytes:
    values = []
    for i in range(N):
        v = scale * (1.0 + 0.5 * math.sin(i / 3000.0 + seed) + 0.01 * ((i * 7919 + seed) % 101))
        if i % 9001 == 17:
            v = -scale * 0.003  # eclipse-like negative excursion
        values.append(v)
    for k in range(n_fill):
        values[(k * 37 + 1000) % N] = xf.FILL_VALUE
    return struct.pack(f"<{N}f", *values)


def synthetic_time(date: str, jitter: float = 0.47) -> bytes:
    import datetime as dt
    day0 = (dt.datetime.fromisoformat(date) - xf.EPOCH).total_seconds()
    return struct.pack(f"<{N}d", *[day0 + jitter + i * 0.99999 for i in range(N)])


def build(*, xrsa: bytes, xrsb: bytes, time: bytes, date: str = DATE, filename: str = NAME,
          license_attr: str = xf.LICENSE_ATTR, a_type: bytes = F32, a_shuffle: int = 4,
          stored_cut: int = 0, drop_xrsb: bool = False) -> bytes:
    w = Writer()
    sb = w.alloc(48)

    def variable(data: bytes, datatype: bytes, element: int, attrs: list[bytes], shuffle_elem: int,
                 cut: int = 0) -> int:
        stored = zlib.compress(shuffle(data, element), 4)
        if cut:
            stored = stored[:-cut]
        chunk = w.add(stored)
        key0 = struct.pack("<II2Q", len(stored), 0, 0, 0)
        key1 = struct.pack("<II2Q", 0, 0, N, element)
        tree = w.add(b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", 1, UNDEF, UNDEF) + key0
                     + struct.pack("<Q", chunk) + key1)
        layout = bytes([3, 2, 2]) + struct.pack("<Q", tree) + struct.pack("<2I", N, element)
        pipeline = bytes([2, 2]) + struct.pack("<HHHI", 2, 1, 1, shuffle_elem) + struct.pack("<HHHI", 1, 1, 1, 4)
        msgs = [(0x01, dataspace((N,))), (0x03, datatype), (0x0B, pipeline), (0x08, layout)]
        msgs += [(0x0C, a) for a in attrs]
        return w.add(ohdr(msgs, 0x00))

    def flux_attrs(long_name: str) -> list[bytes]:
        return [string_attr("units", "W/m2"), string_attr("long_name", long_name),
                attribute("_FillValue", F32, (1,), struct.pack("<f", xf.FILL_VALUE))]

    targets = {
        "xrsa_flux": variable(xrsa, a_type, 4, flux_attrs("Primary XRS-A channel flux."), a_shuffle, stored_cut),
        "time": variable(time, F64, 8, [string_attr("units", "seconds since 2000-01-01 12:00:00 UTC")], 8),
        # decoy with an identical layout: must never be selected for xrsb_flux
        "xrsb1_flux": variable(xrsa, F32, 4, flux_attrs("XRS-B1 flux."), 4),
    }
    if not drop_xrsb:
        targets["xrsb_flux"] = variable(xrsb, F32, 4, flux_attrs("Primary XRS-B channel flux."), 4)
    names = list(targets)

    # Dense links: one direct block, name and creation-order v2 B-trees.
    heap_addr = w.alloc(146)
    block_size = 512
    block_addr = w.alloc(block_size)
    objects = b""
    position = 21
    ids = {}
    for order, name in enumerate(names):
        raw_name = name.encode()
        payload = bytes([1, 0x04]) + struct.pack("<Q", order) + bytes([len(raw_name)]) + raw_name + struct.pack("<Q", targets[name])
        ids[name] = heap_id(position, len(payload), 7)
        objects += payload
        position += len(payload)
    w.put(block_addr, direct_block(heap_addr, block_size, objects))
    w.put(heap_addr, heap_header(7, 512, block_size, 4096, block_addr, len(names)))
    name_records = sorted(struct.pack("<I", lookup3(n.encode())) + ids[n] for n in names)
    name_bt = w.add(bthd(5, 11, w.add(btlf(5, name_records)), len(names)))
    order_bt = w.add(bthd(6, 15, w.add(btlf(6, [struct.pack("<Q", i) + ids[n] for i, n in enumerate(names)])), len(names)))

    # Dense root attributes.
    globals_ = [string_attr(k, v) for k, v in xf.EXPECTED_GLOBALS.items() if k != "license"]
    globals_ += [string_attr("license", license_attr), string_attr("id", filename),
                 string_attr("time_coverage_start", f"{date}T00:00:00.000Z")]
    a_heap = w.alloc(146)
    a_block = w.alloc(2048)
    a_objects = b""
    a_records = []
    position = 21
    for order, payload in enumerate(globals_):
        attr_name = payload[9:9 + struct.unpack_from("<H", payload, 2)[0] - 1]
        a_records.append(heap_id(position, len(payload), 8) + bytes([0]) + struct.pack("<II", order, lookup3(attr_name)))
        a_objects += payload
        position += len(payload)
    w.put(a_block, direct_block(a_heap, 2048, a_objects))
    w.put(a_heap, heap_header(8, 4096, 2048, 65536, a_block, len(globals_)))
    a_bt = w.add(bthd(8, 17, w.add(btlf(8, a_records)), len(globals_)))

    link_info = bytes([0, 0x03]) + struct.pack("<QQQQ", len(names), heap_addr, name_bt, order_bt)
    attr_info = bytes([0, 0]) + struct.pack("<QQ", a_heap, a_bt)
    root = w.add(ohdr([(0x02, link_info), (0x0A, b"\x00\x00"), (0x15, attr_info)], 0x05))
    w.put(sb, checksummed(b"\x89HDF\r\n\x1a\n" + bytes([2, 8, 8, 0]) + struct.pack("<4Q", 0, UNDEF, len(w.buf), root)))
    return bytes(w.buf)


def expect_failure(label: str, func) -> None:
    try:
        func()
    except (h5lite.H5Error, xf.RecipeError, struct.error, KeyError, IndexError, ValueError, zlib.error, SystemExit):
        return
    raise SystemExit(f"selftest: {label} was not rejected")


def main() -> None:
    assert lookup3(b"Four score and seven years ago") == 0x17770551
    xrsa = synthetic_flux(1e-8, 3, 1)
    xrsb = synthetic_flux(1e-7, 481, 2)
    time = synthetic_time(DATE)
    good = build(xrsa=xrsa, xrsb=xrsb, time=time)

    # Shuffle round trip.
    if xf.unshuffle(shuffle(xrsa, 4), 4) != xrsa:
        raise SystemExit("selftest: unshuffle is not the inverse of shuffle")

    for index in ("name", "creation_order"):
        payloads, meta = xf.decode_day(good, NAME, DATE, index)
        if payloads["goes16_xrsa_flux_1s_f32"] != xrsa or payloads["goes16_xrsb_flux_1s_f32"] != xrsb:
            raise SystemExit(f"selftest: build decode differs ({index})")
        if meta["checked_metadata_blocks"] < 10:
            raise SystemExit("selftest: too few checksummed blocks visited")
    vpayloads = verify_xrs.decode(good, NAME, DATE)
    if vpayloads["goes16_xrsa_flux_1s_f32"] != xrsa or vpayloads["goes16_xrsb_flux_1s_f32"] != xrsb:
        raise SystemExit("selftest: verify decode differs")

    prof = xf.profile(xrsb)
    cls = verify_xrs.classify(xrsb)
    if prof["fill_count"] != 481 or cls["fill"] != 481 or prof["nan_count"] != 0 or cls["nan"] != 0:
        raise SystemExit("selftest: fill accounting wrong")
    if (prof["min"], prof["max"], prof["distinct_valid"]) != (cls["min"], cls["max"], cls["distinct"]):
        raise SystemExit("selftest: build/verify profiles disagree")
    if prof["negative_count"] == 0 or prof["min"] >= 0:
        raise SystemExit("selftest: negative values not preserved")
    nan_day = bytearray(xrsa)
    nan_day[0:4] = struct.pack("<I", 0x7FC00000)
    if xf.profile(bytes(nan_day))["nan_count"] != 1 or verify_xrs.classify(bytes(nan_day))["nan"] != 1:
        raise SystemExit("selftest: NaN accounting wrong")
    if not xf.day_is_kept({"a": xf.profile(xrsa), "b": prof})[0]:
        raise SystemExit("selftest: normal day rejected")
    mostly_fill = synthetic_flux(1e-7, 0, 3)
    mostly_fill = xf.FILL_BITS * (N // 2 + 1) + mostly_fill[4 * (N // 2 + 1):]
    if xf.day_is_kept({"a": xf.profile(xrsa), "b": xf.profile(mostly_fill)})[0]:
        raise SystemExit("selftest: fill-dominated day kept")
    if xf.day_is_kept({"a": xf.profile(struct.pack("<f", 1e-8) * N)})[0]:
        raise SystemExit("selftest: constant day kept")
    inf_day = bytearray(xrsa)
    inf_day[8:12] = struct.pack("<f", math.inf)
    expect_failure("infinite value (build)", lambda: xf.profile(bytes(inf_day)))
    expect_failure("infinite value (verify)", lambda: verify_xrs.classify(bytes(inf_day)))

    expect_failure("wrong date", lambda: xf.decode_day(good, NAME, "2022-06-02"))
    expect_failure("wrong filename", lambda: xf.decode_day(good, NAME.replace("0601", "0602"), DATE))
    expect_failure("wrong license", lambda: xf.decode_day(build(xrsa=xrsa, xrsb=xrsb, time=time, license_attr="x"), NAME, DATE))
    expect_failure("big-endian float", lambda: xf.decode_day(build(xrsa=xrsa, xrsb=xrsb, time=time, a_type=F32_BE), NAME, DATE))
    expect_failure("shuffle element 2", lambda: xf.decode_day(build(xrsa=xrsa, xrsb=xrsb, time=time, a_shuffle=2), NAME, DATE))
    expect_failure("verify shuffle element 2", lambda: verify_xrs.decode(build(xrsa=xrsa, xrsb=xrsb, time=time, a_shuffle=2), NAME, DATE))
    expect_failure("truncated chunk", lambda: xf.decode_day(build(xrsa=xrsa, xrsb=xrsb, time=time, stored_cut=9), NAME, DATE))
    expect_failure("verify truncated chunk", lambda: verify_xrs.decode(build(xrsa=xrsa, xrsb=xrsb, time=time, stored_cut=9), NAME, DATE))
    expect_failure("missing xrsb_flux", lambda: xf.decode_day(build(xrsa=xrsa, xrsb=xrsb, time=time, drop_xrsb=True), NAME, DATE))
    backwards = struct.pack(f"<{N}d", *reversed(struct.unpack(f"<{N}d", time)))
    expect_failure("decreasing time", lambda: xf.decode_day(build(xrsa=xrsa, xrsb=xrsb, time=backwards), NAME, DATE))
    shifted = synthetic_time("2022-06-02")
    expect_failure("time outside day", lambda: xf.decode_day(build(xrsa=xrsa, xrsb=xrsb, time=shifted), NAME, DATE))
    for marker in (b"FHDB", b"FRHP", b"BTHD", b"BTLF", b"TREE", b"OHDR"):
        corrupt = bytearray(good)
        pos = corrupt.rfind(marker) + (5 if marker == b"TREE" else 9)
        corrupt[pos] ^= 0x55
        for index in ("name", "creation_order"):
            expect_failure(f"corrupted {marker.decode()} ({index})",
                           lambda c=bytes(corrupt), i=index: xf.decode_day(c, NAME, DATE, i))
    print("selftest=ok synthetic XRS HDF5 decode, missing-value policy and rejection checks passed")


if __name__ == "__main__":
    main()
