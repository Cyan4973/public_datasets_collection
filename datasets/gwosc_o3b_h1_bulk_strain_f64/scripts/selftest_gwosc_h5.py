#!/usr/bin/env python3
"""Self-test for gwosc_h5 / gwosc_strain on synthetic HDF5 files (no network).

The synthetic file mirrors the GWOSC bulk layout confirmed on the real
H-H1_GWOSC_O3b_4KHZ_R1-*.hdf5 files: superblock v0, version-1 object headers,
symbol-table groups /meta, /quality/simple, /strain; scalar variable-length
UTF-8 string datasets held in a global heap collection (GCOL); scalar int64
datasets; a fixed-length string array (DQShortnames); and rank-1 chunked
datasets (uint32 DQmask, float64 Strain) with the [deflate, fletcher32]
filter pipeline indexed by multi-level version-1 chunk B-trees.  Checksums are
written with the literal port of HDF5's H5_checksum_fletcher32, so the bulk
modulo-65535 check in the reader is tested against an independent oracle.
The strain size is reduced (the real file has 16,777,216 values in 2048 chunks
of 8192; that count is re-checked on every real file at download time).
"""
from __future__ import annotations

import math
import os
import random
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gwosc_h5  # noqa: E402
import gwosc_strain  # noqa: E402

UNDEF = 0xFFFFFFFFFFFFFFFF
F64_TYPE = bytes([0x11, 0x20, 0x3F, 0x00]) + struct.pack("<IHHBBBBI", 8, 0, 64, 52, 11, 0, 52, 1023)
I64_TYPE = bytes([0x10, 0x08, 0x00, 0x00]) + struct.pack("<IHH", 8, 0, 64)
U32_TYPE = bytes([0x10, 0x00, 0x00, 0x00]) + struct.pack("<IHH", 4, 0, 32)
VLEN_STR_TYPE = bytes.fromhex("190101001000000010000000010000000000080000000000")


def str_type(size: int) -> bytes:
    return bytes([0x13, 0x00, 0x00, 0x00]) + struct.pack("<I", size)


def pad8(b: bytes) -> bytes:
    return b + b"\x00" * ((-len(b)) % 8)


class Writer:
    def __init__(self) -> None:
        self.buf = bytearray(96)

    def alloc(self, data: bytes, align: int = 8) -> int:
        self.buf += b"\x00" * ((-len(self.buf)) % align)
        addr = len(self.buf)
        self.buf += data
        return addr


def msg(mtype: int, payload: bytes) -> bytes:
    payload = pad8(payload)
    return struct.pack("<HHB3x", mtype, len(payload), 0) + payload


def object_header(messages: list[bytes]) -> bytes:
    body = b"".join(messages)
    return struct.pack("<BBHII4x", 1, 0, len(messages), 1, len(body)) + body


def dataspace(dims: tuple[int, ...]) -> bytes:
    return struct.pack("<BBBB4x", 1, len(dims), 0, 0) + b"".join(struct.pack("<Q", d) for d in dims)


def attribute(name: str, dtype: bytes, fmt: str, value) -> bytes:
    nb = name.encode() + b"\x00"
    sp = dataspace((1,))
    return (struct.pack("<BBHHH", 1, 0, len(nb), len(dtype), len(sp)) + pad8(nb) + pad8(dtype) + pad8(sp)
            + struct.pack("<" + fmt, value))


def filters_msg() -> bytes:
    out = struct.pack("<BB6x", 1, 2)
    for fid, name, flags, vals in ((1, b"deflate\x00", 1, (1,)), (3, b"fletcher32\x00", 0, ())):
        out += struct.pack("<4H", fid, len(name), flags, len(vals)) + pad8(name)
        out += b"".join(struct.pack("<I", v) for v in vals) + (b"\x00" * 4 if len(vals) % 2 else b"")
    return out


def contiguous(w: Writer, dtype: bytes, dims: tuple[int, ...], data: bytes) -> int:
    addr = w.alloc(data)
    return w.alloc(object_header([msg(0x01, dataspace(dims)), msg(0x03, dtype),
                                  msg(0x08, struct.pack("<BBQQ", 3, 1, addr, len(data)))]))


def stored_chunk(raw: bytes, level: int = 1) -> bytes:
    comp = zlib.compress(raw, level)
    return comp + struct.pack("<I", gwosc_h5.fletcher32_reference(comp))


def chunk_btree(w: Writer, entries: list[tuple[int, int, int]], n: int, fanout: int) -> int:
    """entries: (stored size, element offset, address); two levels when > fanout."""
    def key(size: int, off: int) -> bytes:
        return struct.pack("<IIQQ", size, 0, off, 0)

    def node(level: int, items: list[tuple[bytes, int]], last: bytes) -> bytes:
        out = b"TREE" + struct.pack("<BBHQQ", 1, level, len(items), UNDEF, UNDEF)
        return out + b"".join(k + struct.pack("<Q", c) for k, c in items) + last

    final = key(0, n)
    leaves = [entries[i:i + fanout] for i in range(0, len(entries), fanout)]
    if len(leaves) == 1:
        return w.alloc(node(0, [(key(s, o), a) for s, o, a in leaves[0]], final))
    tops = []
    for i, group in enumerate(leaves):
        last = key(0, leaves[i + 1][0][1]) if i + 1 < len(leaves) else final
        tops.append((key(group[0][0], group[0][1]), w.alloc(node(0, [(key(s, o), a) for s, o, a in group], last))))
    return w.alloc(node(1, tops, final))


def chunked(w: Writer, dtype: bytes, esize: int, raw: bytes, chunk: int, attrs: list[bytes], fanout: int,
            chunk_order: list[int] | None = None) -> int:
    n = len(raw) // esize
    entries = []
    starts = list(range(0, n, chunk))
    for s in (chunk_order and [starts[i] for i in chunk_order]) or starts:  # physical write order
        piece = raw[s * esize:(s + chunk) * esize]
        piece += b"\x00" * (chunk * esize - len(piece))
        st = stored_chunk(piece)
        entries.append((len(st), s, w.alloc(st, 1)))
    entries.sort(key=lambda e: e[1])
    bt = chunk_btree(w, entries, n, fanout)
    layout = struct.pack("<BBBQ2I", 3, 2, 2, bt, chunk, esize)
    return w.alloc(object_header([msg(0x01, dataspace((n,))), msg(0x03, dtype), msg(0x0B, filters_msg()),
                                  msg(0x08, layout)] + [msg(0x0C, a) for a in attrs]))


def group(w: Writer, links: dict[str, int], snod_cap: int = 4) -> int:
    names = sorted(links)
    heap = bytearray(b"\x00" * 8)
    offs = {}
    for name in names:
        offs[name] = len(heap)
        heap += pad8(name.encode() + b"\x00")
    data_addr = w.alloc(bytes(heap))
    heap_addr = w.alloc(b"HEAP" + struct.pack("<B3xQQQ", 0, len(heap), UNDEF, data_addr))
    children = []
    for i in range(0, len(names), snod_cap):
        g = names[i:i + snod_cap]
        body = b"SNOD" + struct.pack("<BBH", 1, 0, len(g))
        body += b"".join(struct.pack("<QQII16x", offs[nm], links[nm], 0, 0) for nm in g)
        children.append((offs[g[-1]], w.alloc(body)))
    tree = b"TREE" + struct.pack("<BBHQQ", 0, 0, len(children), UNDEF, UNDEF) + struct.pack("<Q", 0)
    tree += b"".join(struct.pack("<QQ", c, k) for k, c in children)
    root = w.alloc(tree)
    return w.alloc(object_header([msg(0x11, struct.pack("<QQ", root, heap_addr))]))


def gcol(w: Writer, strings: list[str]) -> tuple[int, dict[str, int]]:
    body = b""
    idx = {}
    for i, s in enumerate(strings, 1):
        data = s.encode()
        body += struct.pack("<HHIQ", i, 1, 0, len(data)) + pad8(data)
        idx[s] = i
    body += struct.pack("<HHIQ", 0, 0, 0, 16)  # free-space object
    total = 16 + len(body)
    return w.alloc(b"GCOL" + struct.pack("<B3xQ", 1, total) + body), idx


def build_file(gps: int, strain: list[float], dq: list[int], chunk: int, channel: str,
               chunk_order: list[int] | None = None) -> bytes:
    w = Writer()
    meta_s = {"StrainChannel": channel, "Detector": "H1", "FrameType": gwosc_strain.FRAME_TYPE,
              "Type": "StrainTimeSeries", "Observatory": "H", "Description": "Strain data time series from LIGO"}
    coll, idx = gcol(w, list(dict.fromkeys(meta_s.values())))
    meta = {k: contiguous(w, VLEN_STR_TYPE, (), struct.pack("<IQI", len(v.encode()), coll, idx[v]))
            for k, v in meta_s.items()}
    meta["GPSstart"] = contiguous(w, I64_TYPE, (), struct.pack("<q", gps))
    meta["Duration"] = contiguous(w, I64_TYPE, (), struct.pack("<q", gwosc_strain.DURATION))
    names = ["DATA", "CBC_CAT1", "CBC_CAT2", "CBC_CAT3", "BURST_CAT1", "BURST_CAT2", "BURST_CAT3"]
    simple = {
        "DQShortnames": contiguous(w, str_type(10), (7,), b"".join(n.encode().ljust(10, b"\x00") for n in names)),
        "DQmask": chunked(w, U32_TYPE, 4, struct.pack(f"<{len(dq)}I", *dq), 1024, [], fanout=3),
    }
    rate = gwosc_strain.RATE
    sattrs = [attribute("Npoints", I64_TYPE, "q", len(strain)), attribute("Xspacing", F64_TYPE, "d", 1.0 / rate),
              attribute("Xstart", I64_TYPE, "q", gps)]
    st = {"Strain": chunked(w, F64_TYPE, 8, struct.pack(f"<{len(strain)}d", *strain), chunk, sattrs, fanout=5,
                            chunk_order=chunk_order)}
    root = group(w, {"meta": group(w, meta), "quality": group(w, {"simple": group(w, simple)}),
                     "strain": group(w, st)})
    eof = len(w.buf)
    sb = (gwosc_h5.HDF5_SIGNATURE + bytes([0, 0, 0, 0, 0, 8, 8, 0]) + struct.pack("<HHI", 4, 16, 0)
          + struct.pack("<4Q", 0, UNDEF, eof, UNDEF) + struct.pack("<QQII16x", 0, root, 1, 0))
    w.buf[0:96] = sb
    return bytes(w.buf)


def colored_noise(n: int, seed: int) -> list[float]:
    rnd = random.Random(seed)
    out, x = [], 0.0
    for i in range(n):
        x = 0.995 * x + rnd.gauss(0, 1e-20)
        out.append(x + 3e-21 * math.sin(0.37 * i))
    return out


def row_for(gps: int, strain: list[float], size: int) -> dict:
    n = len(strain)
    mean = math.fsum(strain) / n
    std = math.sqrt(math.fsum((v - mean) ** 2 for v in strain) / n)
    return {"gps_start": gps, "utc_start": "2019-12-03T02:50:22", "size_bytes": size,
            "url": f"https://gwosc.org/archive/data/O3b_4KHZ_R1/0/H-H1_GWOSC_O3b_4KHZ_R1-{gps}-4096.hdf5",
            "gwosc_min_strain": repr(min(strain)), "gwosc_max_strain": repr(max(strain)),
            "gwosc_mean_strain": repr(mean), "gwosc_stdev_strain": repr(std)}


def expect_fail(fn, what: str, needle: str) -> None:
    try:
        fn()
    except (gwosc_h5.H5Error, SystemExit) as exc:
        if needle not in str(exc):
            raise AssertionError(f"{what}: failed for the wrong reason: {exc}") from exc
        return
    raise AssertionError(f"expected failure: {what}")


def main() -> int:
    # 1. Fletcher-32: bulk modulo check vs the literal HDF5 port
    rnd = random.Random(7)
    for n in (0, 1, 2, 3, 359 * 2, 720, 721, 1441, 5000, 65537):
        data = bytes(rnd.getrandbits(8) for _ in range(n))
        ref = gwosc_h5.fletcher32_reference(data)
        assert gwosc_h5.fletcher32_matches(data, ref), n
        if n > 4:
            assert not gwosc_h5.fletcher32_matches(data, ref ^ 0x00010000), n
    big = b"\xff" * 4000  # sums that hit 0 mod 65535 (0xffff vs 0 representation)
    assert gwosc_h5.fletcher32_matches(big, gwosc_h5.fletcher32_reference(big))
    print("selftest: fletcher32 bulk check agrees with the HDF5 reference")

    # 2. reduced-size synthetic GWOSC file through the full validation path
    gwosc_strain.RATE = 8
    gwosc_strain.NPOINTS = gwosc_strain.DURATION * gwosc_strain.RATE  # 32768
    gwosc_strain.CHUNK = 1024
    gps = 1259376640
    strain = colored_noise(gwosc_strain.NPOINTS, 1)
    dq = [127 if i % 3 else 31 for i in range(gwosc_strain.DURATION)]
    order = list(range(32))
    random.Random(3).shuffle(order)
    data = build_file(gps, strain, dq, 1024, gwosc_strain.CHANNEL, chunk_order=order)
    want = struct.pack(f"<{len(strain)}d", *strain)
    with tempfile.TemporaryDirectory(prefix="gwosc_selftest_") as tmp:
        tmp = Path(tmp)

        def check(blob: bytes, row: dict) -> bytes:
            p = tmp / "f.hdf5"
            p.write_bytes(blob)
            out = bytearray()
            gwosc_strain.decode_file(p, row, out.extend)
            return bytes(out)

        row = row_for(gps, strain, len(data))
        got = check(data, row)
        assert got == want, "decoded strain differs"
        f = gwosc_h5.H5File(data)
        assert f.read_scalar("meta/StrainChannel") == gwosc_strain.CHANNEL
        assert f.read_scalar("meta/Description") == "Strain data time series from LIGO"
        assert f.read_scalar("meta/GPSstart") == gps
        info = f.dataset(f.resolve("strain/Strain"))
        assert info["attributes"]["Xspacing"] == [0.125] and info["chunk_dims"] == (1024,)
        print(f"selftest: synthetic file decodes byte-exact ({len(strain)} values, {len(data)} bytes, "
              "out-of-order chunks, 2-level chunk B-tree)")

        # 3. rejections
        bad = bytearray(data)
        size, _m, _o, addr = f.chunk_entries(info["chunk_btree"], 1)[7]
        bad[addr + size // 3] ^= 0x10
        expect_fail(lambda: check(bytes(bad), row), "corrupted chunk", "Fletcher-32 checksum mismatch")
        blob_l1 = build_file(gps, strain, dq, 1024, "L1:DCS-CALIB_STRAIN_CLEAN_SUB60HZ_C01")
        expect_fail(lambda: check(blob_l1, row | {"size_bytes": len(blob_l1)}), "wrong channel", "meta")
        dq_bad = list(dq)
        dq_bad[100] = 0
        blob = build_file(gps, strain, dq_bad, 1024, gwosc_strain.CHANNEL)
        expect_fail(lambda: check(blob, row_for(gps, strain, len(blob))), "missing DATA bit", "lack the DQ DATA bit")
        s_nan = list(strain)
        s_nan[5000] = float("nan")
        blob_nan = build_file(gps, s_nan, dq, 1024, gwosc_strain.CHANNEL)
        expect_fail(lambda: check(blob_nan, row | {"size_bytes": len(blob_nan)}), "NaN value", "non-finite")
        s_inf = list(strain)
        s_inf[7000] = float("-inf")
        blob_inf = build_file(gps, s_inf, dq, 1024, gwosc_strain.CHANNEL)
        expect_fail(lambda: check(blob_inf, row | {"size_bytes": len(blob_inf)}), "inf value", "non-finite")
        s_zero = list(strain)
        s_zero[2048:3072] = [0.0] * 1024
        blob = build_file(gps, s_zero, dq, 1024, gwosc_strain.CHANNEL)
        expect_fail(lambda: check(blob, row_for(gps, s_zero, len(blob))), "all-zero chunk", "all-zero chunk")
        s_rep = list(strain)
        s_rep[3072:4096] = s_rep[2048:3072]
        blob = build_file(gps, s_rep, dq, 1024, gwosc_strain.CHANNEL)
        expect_fail(lambda: check(blob, row_for(gps, s_rep, len(blob))), "repeated chunk", "repeats")
        expect_fail(lambda: check(data, row | {"gwosc_max_strain": repr(max(strain) * 1.001)}),
                    "GWOSC max mismatch", "GWOSC published")
        expect_fail(lambda: check(data, row | {"gwosc_stdev_strain": repr(float(row["gwosc_stdev_strain"]) * 1.01)}),
                    "GWOSC stdev mismatch", "stdev")
        expect_fail(lambda: check(data, row | {"gps_start": gps + 4096}), "GPS mismatch", "meta")
        expect_fail(lambda: check(data, row | {"size_bytes": len(data) + 1}), "size mismatch", "pinned")
        blob = build_file(gps, strain[:-1024], dq, 1024, gwosc_strain.CHANNEL)
        expect_fail(lambda: check(blob, row_for(gps, strain[:-1024], len(blob))), "short strain", "shape")
        expect_fail(lambda: gwosc_h5.H5File(data[:8] + b"\x02" + data[9:]), "superblock v2", "superblock version")
    print("selftest: rejection checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
