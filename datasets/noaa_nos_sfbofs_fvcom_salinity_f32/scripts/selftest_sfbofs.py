#!/usr/bin/env python3
"""Synthetic self-test for the SFBOFS salinity range-decode path.

Builds small NetCDF4/HDF5 files shaped like sfbofs.t03z.*.fields.n003.nc from
scratch: superblock v0, a version-2 root object header whose links live in
dense storage (fractal heap with a checksummed root direct block, indexed by a
version-2 name B-tree), compact global/variable attributes, a raw (unfiltered)
float32 ``salinity`` dataset of shape (1, siglay, node) chunked
(1, siglay/2, node/2) with a version-1 chunk B-tree placed directly before its
chunks (so the fetched B-tree window overlaps chunk 0, as in the real files),
an unfiltered chunked float64 ``time`` and contiguous adjacent ``x``/``y``.

It then simulates the download: only the planned ranges (head, B-tree
windows, x/y, chunks) are cut from the synthetic file into segment files, and
the decoder must reproduce the original float32 field through both assembly
routes.  Corrupted and out-of-scope variants and degenerate value fields must
be rejected.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import struct
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fvcom_h5 as h5  # noqa: E402
import sfbofs_salinity as ss  # noqa: E402
from fvcom_h5 import UNDEF, lookup3  # noqa: E402

F64_LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
I32 = bytes.fromhex("100800000400000000002000")
N_L, N_N, CL, CN = 4, 10, 2, 5
META = 16384
DATE = "2025-03-05"
LINK_NAMES = ["salinity", "siglay", "time", "x", "y", "temp", "h", "zeta"]


def dataspace(dims: tuple[int, ...]) -> bytes:
    if not dims:
        return bytes([2, 0, 0, 0])
    return bytes([2, len(dims), 0, 1]) + struct.pack(f"<{len(dims)}Q", *dims)


def checksummed(body: bytes) -> bytes:
    return body + struct.pack("<I", lookup3(body))


def ohdr(messages: list[tuple[int, bytes]]) -> bytes:
    body = b"".join(struct.pack("<BHB", t, len(p), 0) + p for t, p in messages)
    return checksummed(b"OHDR" + bytes([2, 0x02]) + struct.pack("<I", len(body)) + body)


def attribute(name: str, datatype: bytes, dims: tuple[int, ...], data: bytes) -> bytes:
    raw_name = name.encode() + b"\x00"
    space = dataspace(dims)
    return (bytes([3, 0]) + struct.pack("<HHH", len(raw_name), len(datatype), len(space)) + b"\x00"
            + raw_name + datatype + space + data)


def attr_value(name: str, value) -> bytes:
    if isinstance(value, str):
        raw = value.encode()
        return attribute(name, bytes([0x13, 0, 0, 0]) + struct.pack("<I", len(raw)), (), raw)
    return attribute(name, I32, (len(value),), struct.pack(f"<{len(value)}i", *value))


class Writer:
    """Metadata goes to [0, META); raw data is appended from META on."""

    def __init__(self) -> None:
        self.buf = bytearray(META)
        self.meta = 0

    def meta_add(self, data: bytes) -> int:
        self.meta = (self.meta + 7) & ~7
        addr = self.meta
        if addr + len(data) > META:
            raise RuntimeError("synthetic metadata overflows META")
        self.buf[addr:addr + len(data)] = data
        self.meta += len(data)
        return addr

    def meta_reserve(self, size: int) -> int:
        return self.meta_add(b"\x00" * size)

    def data_add(self, data: bytes) -> int:
        while len(self.buf) % 8:
            self.buf.append(0)
        addr = len(self.buf)
        self.buf.extend(data)
        return addr

    def put(self, addr: int, data: bytes) -> None:
        self.buf[addr:addr + len(data)] = data


def synthetic_field() -> list[float]:
    vals = []
    for layer in range(N_L):
        for node in range(N_N):
            vals.append(round(18.0 + 9.0 * math.sin(node * 0.7 + 0.3) + 0.45 * layer + 0.01 * node * layer, 3))
    return vals


def synthetic_xy() -> bytes:
    x = struct.pack(f"<{N_N}f", *[550000.0 + 125.5 * n for n in range(N_N)])
    y = struct.pack(f"<{N_N}f", *[4180000.0 - 77.25 * n for n in range(N_N)])
    return x + y


def synthetic_spec() -> dict:
    spec = dict(ss.REAL_SPEC)
    spec.update({
        "head_len": META,
        "n_siglay": N_L,
        "n_node": N_N,
        "sal_chunk": (1, CL, CN),
        "n_links": len(LINK_NAMES),
        "links_sha256": hashlib.sha256("\n".join(sorted(LINK_NAMES)).encode()).hexdigest(),
        "xy_sha256": hashlib.sha256(synthetic_xy()).hexdigest(),
        "min_distinct": 30,
    })
    return spec


def build(values: list[float], *, date: str = DATE, filters: bool = False, f64: bool = False,
          mask_chunk: int | None = None, drop_chunk: bool = False, time_shift: float = 0.0,
          perturb_xy: bool = False, extra_link: bool = False, sal_fill_attr: bool = False,
          raw_values: bytes | None = None) -> tuple[bytes, int]:
    w = Writer()
    w.meta_reserve(96)  # superblock
    spec = synthetic_spec()

    # raw data region: x/y, time chunk index + chunk, salinity chunk index + chunks
    xy = bytearray(synthetic_xy())
    if perturb_xy:
        xy[5] ^= 0x01
    x_addr = w.data_add(bytes(xy[:4 * N_N]))
    y_addr = w.data_add(bytes(xy[4 * N_N:]))
    assert y_addr == x_addr + 4 * N_N
    tval = ss.expected_time(date) + time_shift
    tchunk = struct.pack("<d", tval) + b"\x00" * (8 * 511)
    tnode_size = 24 + 1 * 32 + 24
    t_btree = w.data_add(b"\x00" * tnode_size)
    t_chunk = w.data_add(tchunk)
    w.put(t_btree, b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", 1, UNDEF, UNDEF)
          + struct.pack("<II2Q", len(tchunk), 0, 0, 0) + struct.pack("<Q", t_chunk)
          + struct.pack("<II2Q", 0, 0, 512, 8))

    payload = raw_values if raw_values is not None else struct.pack(f"<{len(values)}f", *values)
    grid = [(l0, n0) for l0 in range(0, N_L, CL) for n0 in range(0, N_N, CN)]
    entries = grid[:-1] if drop_chunk else grid
    s_btree = w.data_add(b"\x00" * (24 + len(entries) * 48 + 40))
    chunk_rows = []
    for i, (l0, n0) in enumerate(entries):
        chunk = b"".join(payload[4 * ((l0 + li) * N_N + n0): 4 * ((l0 + li) * N_N + n0 + CN)] for li in range(CL))
        addr = w.data_add(chunk)
        chunk_rows.append((len(chunk), 1 if mask_chunk == i else 0, (0, l0, n0, 0), addr))
    node = b"TREE" + bytes([1, 0]) + struct.pack("<HQQ", len(chunk_rows), UNDEF, UNDEF)
    for size, mask, offs, addr in chunk_rows:
        node += struct.pack("<II4Q", size, mask, *offs) + struct.pack("<Q", addr)
    node += struct.pack("<II4Q", 0, 0, 1, N_L, N_N, 4)
    w.put(s_btree, node)

    # dataset object headers (metadata region)
    f32 = F64_LE if f64 else ss.F32_LE
    sal_msgs = [(0x01, dataspace((1, N_L, N_N))), (0x03, f32)]
    if filters:
        sal_msgs.append((0x0B, bytes([2, 1]) + struct.pack("<HHHI", 1, 1, 1, 4)))
    sal_msgs.append((0x08, bytes([3, 2, 4]) + struct.pack("<Q", s_btree) + struct.pack("<4I", 1, CL, CN, 4)))
    sal_attrs = dict(spec["sal_attrs"])
    sal_attrs["coordinates"] = "time siglay lat lon"
    if sal_fill_attr:
        sal_attrs["_FillValue"] = "x"
    sal_msgs += [(0x0C, attr_value(k, v)) for k, v in sal_attrs.items()]
    targets = {"salinity": w.meta_add(ohdr(sal_msgs))}

    def contiguous(dims, datatype, addr, size) -> int:
        layout = bytes([3, 1]) + struct.pack("<QQ", addr, size)
        return w.meta_add(ohdr([(0x01, dataspace(dims)), (0x03, datatype), (0x08, layout)]))

    targets["siglay"] = contiguous((N_L, N_N), ss.F32_LE, UNDEF, 4 * N_L * N_N)
    targets["time"] = w.meta_add(ohdr([
        (0x01, dataspace((1,))), (0x03, F64_LE),
        (0x08, bytes([3, 2, 2]) + struct.pack("<Q", t_btree) + struct.pack("<2I", 512, 8)),
        (0x0C, attr_value("units", spec["time_units"])),
    ]))
    targets["x"] = contiguous((N_N,), ss.F32_LE, x_addr, 4 * N_N)
    targets["y"] = contiguous((N_N,), ss.F32_LE, y_addr, 4 * N_N)
    for name in ("temp", "h", "zeta"):
        targets[name] = contiguous((N_N,), ss.F32_LE, UNDEF, 4 * N_N)
    if extra_link:
        targets["salinity_decoy"] = targets["salinity"]

    # dense link storage: fractal heap (one checksummed direct block) + v2 name B-tree
    id_len, start_block, max_direct, width, heap_bits = 8, 4096, 65536, 4, 32
    off_size, len_size = 4, 2
    heap_addr = w.meta_reserve(5 + 4 + 1 + 4 + 96 + 2 + 16 + 4 + 8 + 2 + 4)
    block_addr = w.meta_reserve(start_block)
    block = bytearray(start_block)
    hdr_len = 13 + off_size + 4
    block[:hdr_len] = b"FHDB" + bytes([0]) + struct.pack("<Q", heap_addr) + (0).to_bytes(off_size, "little") + b"\x00" * 4
    pos = hdr_len
    heap_ids = []
    for name, target in targets.items():
        raw = name.encode()
        msg = bytes([1, 0x00, len(raw)]) + raw + struct.pack("<Q", target)
        block[pos:pos + len(msg)] = msg
        hid = bytes([0]) + pos.to_bytes(off_size, "little") + len(msg).to_bytes(len_size, "little")
        heap_ids.append((name, hid + b"\x00" * (id_len - len(hid))))
        pos += len(msg)
    struct.pack_into("<I", block, 13 + off_size, lookup3(bytes(block)))
    w.put(block_addr, bytes(block))
    fields = (0, UNDEF, start_block - pos, UNDEF, start_block, start_block, pos, len(targets), 0, 0, 0, 0)
    heap = (b"FRHP" + bytes([0]) + struct.pack("<HHBI", id_len, 0, 0x02, 4096) + struct.pack("<12Q", *fields)
            + struct.pack("<HQQHHQH", width, start_block, max_direct, heap_bits, 0, block_addr, 0))
    w.put(heap_addr, checksummed(heap))
    records = b"".join(struct.pack("<I", lookup3(n.encode())) + hid for n, hid in heap_ids)
    leaf_addr = w.meta_reserve(512)
    w.put(leaf_addr, checksummed(b"BTLF" + bytes([0, 5]) + records))
    bthd = checksummed(b"BTHD" + bytes([0, 5]) + struct.pack("<IHHBBQHQ", 512, 4 + id_len, 0, 100, 40,
                                                            leaf_addr, len(heap_ids), len(heap_ids)))
    bthd_addr = w.meta_add(bthd)
    link_info = bytes([0, 0x00]) + struct.pack("<QQ", heap_addr, bthd_addr)
    globals_ = dict(spec["globals"])
    ymd = date.replace("-", "")
    globals_["Surface_Heat_Forcing"] = f"FILE NAME:sfbofs.t03z.{ymd}.hflux.nowcast.nc"
    globals_["history"] = "selftest"
    root_msgs = [(0x02, link_info), (0x0A, b"\x00\x00")] + [(0x0C, attr_value(k, v)) for k, v in globals_.items()]
    root = w.meta_add(ohdr(root_msgs))
    eof = len(w.buf)
    w.put(0, b"\x89HDF\r\n\x1a\n" + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
          + struct.pack("<4Q", 0, UNDEF, eof, UNDEF) + struct.pack("<QQII", 0, root, 0, 0) + b"\x00" * 16)
    return bytes(w.buf), eof


def simulate_download(raw: bytes, spec: dict, date: str, workdir: Path, corrupt_overlap: bool = False) -> Path:
    """Cut only the planned ranges out of the synthetic file, as download.sh does."""
    fdir = workdir / date
    fdir.mkdir(parents=True, exist_ok=True)
    for p in fdir.iterdir():
        p.unlink()

    def cut(plan):
        for name, start, length in plan:
            (fdir / f"{name}.bin").write_bytes(raw[start:start + length])

    cut(ss.head_plan(spec))
    _f, _m, mplan, _c, _d = ss.open_file(fdir, spec, date, "meta")
    cut(mplan)
    _f, _m, _mp, _c, dplan = ss.open_file(fdir, spec, date, "chunks")
    cut(dplan)
    if corrupt_overlap:
        data = bytearray((fdir / "sal_btree.bin").read_bytes())
        data[-1] ^= 0xFF  # tail of the window overlaps chunk 0 / later chunks
        (fdir / "sal_btree.bin").write_bytes(bytes(data))
    return fdir


def expect_failure(label: str, func) -> None:
    try:
        func()
    except ss.DECODE_ERRORS:
        return
    raise SystemExit(f"selftest: {label} was not rejected")


def main() -> None:
    assert lookup3(b"") == 0xDEADBEEF
    assert lookup3(b"Four score and seven years ago") == 0x17770551

    view = h5.Sparse([(0, b"abcdef"), (4, b"efgh")], 10)
    if view[2:6] != b"cdef" or view[5] != ord("f") or view[6:8] != b"gh":
        raise SystemExit("selftest: Sparse view returns wrong bytes")
    expect_failure("read outside fetched ranges", lambda: view[7:9 + 1])
    expect_failure("disagreeing overlap", lambda: h5.Sparse([(0, b"abcdef"), (4, b"xx")], 10))

    spec = synthetic_spec()
    values = synthetic_field()
    expected = struct.pack(f"<{len(values)}f", *values)
    with tempfile.TemporaryDirectory(prefix="sfbofs_selftest_") as tmp:
        work = Path(tmp)
        raw, size = build(values)
        spec_ok = dict(spec, file_size=size)
        fdir = simulate_download(raw, spec_ok, DATE, work)
        fetched = sum(p.stat().st_size for p in fdir.iterdir())
        for route in ("chunk", "layer"):
            payload, info = ss.decode_file(fdir, spec_ok, DATE, route)
            if payload != expected:
                raise SystemExit(f"selftest: decoded field differs (route {route})")
            if info["valid_time_utc"] != f"{DATE}T00:00:00Z":
                raise SystemExit("selftest: valid time wrong")
        if any(name.startswith("sal_c") and start < META for name, start, _l in info["ranges"]):
            raise SystemExit("selftest: chunk ranges should lie outside the head")
        prof = ss.profile(expected, spec_ok)
        stored = [struct.unpack("<f", struct.pack("<f", v))[0] for v in values]
        if prof["min"] != min(stored) or prof["max"] != max(stored):
            raise SystemExit("selftest: min/max must be computed from stored float32")

        # Missing segment: drop one chunk file -> decode must fail (no zero fill).
        (fdir / "sal_c2.bin").unlink()
        expect_failure("missing chunk segment", lambda: ss.decode_file(fdir, spec_ok, DATE))

        def variant(label: str, *, date: str = DATE, decode_date: str | None = None,
                    corrupt_overlap: bool = False, mutate=None, **kw) -> None:
            vraw, vsize = build(values, date=date, **kw)
            if mutate is not None:
                vraw = mutate(vraw)
            vspec = dict(spec, file_size=vsize)

            def run():
                vdir = simulate_download(vraw, vspec, decode_date or date, work / label, corrupt_overlap)
                ss.decode_file(vdir, vspec, decode_date or date)

            expect_failure(label, run)

        variant("deflate filter", filters=True)
        variant("float64 salinity", f64=True)
        variant("filter mask set", mask_chunk=1)
        variant("missing chunk entry", drop_chunk=True)
        variant("shifted time", time_shift=3600.0)
        variant("different mesh", perturb_xy=True)
        variant("extra root link", extra_link=True)
        variant("_FillValue attribute", sal_fill_attr=True)
        variant("wrong cycle date", decode_date="2025-03-12")
        variant("disagreeing overlap bytes", corrupt_overlap=True)

        def flip_ohdr(buf: bytes) -> bytes:
            b = bytearray(buf)
            pos = b.find(b"OHDR") + 20
            b[pos] ^= 0x40
            return bytes(b)

        def flip_heap_block(buf: bytes) -> bytes:
            b = bytearray(buf)
            pos = b.find(b"FHDB") + 40
            b[pos] ^= 0x01
            return bytes(b)

        variant("corrupted object header", mutate=flip_ohdr)
        variant("corrupted heap direct block", mutate=flip_heap_block)

        # Data-level rejections go through the same decode path.
        fill = struct.pack("<I", ss.NC_FILL_F32_BITS)
        nan = struct.pack("<f", float("nan"))
        with_fill = expected[:12] + fill + expected[16:]
        with_nan = expected[:12] + nan + expected[16:]
        layer = expected[:4 * N_N]
        for label, payload in (("fill value", with_fill), ("NaN", with_nan),
                               ("out of range", expected[:8] + struct.pack("<f", 60.0) + expected[12:]),
                               ("constant", struct.pack("<f", 30.0) * (N_L * N_N)),
                               ("modal dominated", struct.pack("<f", 0.05) * (N_L * N_N // 2 + 1)
                                + expected[4 * (N_L * N_N // 2 + 1):]),
                               ):
            expect_failure(f"profile {label}", lambda p=payload: ss.profile(p, spec_ok))
            vraw, vsize = build(values, raw_values=payload)
            vspec = dict(spec, file_size=vsize)
            vdir = simulate_download(vraw, vspec, DATE, work / ("data_" + label.replace(" ", "_")))
            got, _info = ss.decode_file(vdir, vspec, DATE)
            if got != payload:
                raise SystemExit(f"selftest: raw payload variant {label} did not round-trip")
            expect_failure(f"decoded {label}", lambda g=got, s=vspec: ss.profile(g, s))

        # Vertical degeneracy in isolation (distinct floor relaxed so only that rule can trip).
        loose = dict(spec_ok, min_distinct=5)
        ss.profile(expected, loose)
        expect_failure("vertically identical layers", lambda: ss.profile(layer * N_L, loose))
        half = N_L * N_N // 2 + 1
        modal = struct.pack("<f", 0.05) * half + expected[4 * half:]
        try:
            ss.profile(modal, dict(loose, max_modal_fraction=1.0))
        except ss.DECODE_ERRORS as exc:
            raise SystemExit(f"selftest: modal payload should pass with the modal rule disabled: {exc}")
        expect_failure("modal value above half of the sample", lambda: ss.profile(modal, loose))

    # Response-header validation.
    with tempfile.TemporaryDirectory(prefix="sfbofs_selftest_hdr_") as tmp:
        hp = Path(tmp) / "h.txt"
        good = ("HTTP/1.1 200 Connection established\r\n\r\nHTTP/1.1 206 Partial Content\r\n"
                "Content-Range: bytes 10-19/100\r\nContent-Length: 10\r\nETag: \"abc-7\"\r\n\r\n")
        hp.write_text(good)
        ss.check_response(hp, 10, 19, 100, "abc-7")
        for bad in (good.replace("206 Partial Content", "200 OK"), good.replace("abc-7", "abd-7"),
                    good.replace("10-19/100", "10-19/101"), good.replace("Length: 10", "Length: 11")):
            hp.write_text(bad)
            expect_failure("bad response headers", lambda: ss.check_response(hp, 10, 19, 100, "abc-7"))

    print(f"selftest=ok synthetic dense-link HDF5 range decode ({fetched} of {size} bytes fetched), "
          "both assembly routes, rejection and profile checks passed")


if __name__ == "__main__":
    main()
