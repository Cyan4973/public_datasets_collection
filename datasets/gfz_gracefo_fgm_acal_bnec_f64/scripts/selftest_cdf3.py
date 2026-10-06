#!/usr/bin/env python3
"""In-memory self-test of cdf3.py against synthetic CDF v3 files.

Builds whole-file-GZIP-compressed, network-encoded CDFs shaped like the
GRACE-FO ACAL_CORR product (CDF_EPOCH Timestamp, CDF_DOUBLE[3] B_NEC and
B_FGM, CDF_DOUBLE[4] quaternion, CDF_UINT1 flag, CHAR labels, global and
variable attributes) and exercises: CCR/CPR whole-file decompression, VXRnext
chains, nested VXRs, mixed CVVR/VVR leaves, attribute decoding, plus
rejection of record gaps, truncated gzip streams and unsupported encodings.
Writes nothing to disk; exits non-zero on any mismatch.
"""
from __future__ import annotations

import gzip
import math
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdf3  # noqa: E402


class Writer:
    def __init__(self, encoding: int = 1):
        self.buf = bytearray(struct.pack(">II", 0xCDF30001, 0x0000FFFF))
        self.encoding = encoding
        self.order = ">" if encoding == 1 else "<"

    def tell(self) -> int:
        return len(self.buf)

    def add(self, payload: bytes) -> int:
        off = len(self.buf)
        self.buf += payload
        return off

    def patch_q(self, off: int, value: int) -> None:
        struct.pack_into(">q", self.buf, off, value)

    def patch_i(self, off: int, value: int) -> None:
        struct.pack_into(">i", self.buf, off, value)


def name256(text: str) -> bytes:
    return text.encode().ljust(256, b"\x00")


def build(encoding: int = 1, gap: bool = False, truncate_cvvr: bool = False) -> tuple[bytes, dict]:
    w = Writer(encoding)
    order = w.order
    n_rec = 10
    epoch0 = 63877680000000.0
    timestamps = [epoch0 + 1000.0 * i for i in range(n_rec)]
    b_nec = [((-1) ** i) * (12345.678901234567 + i * 0.1234567890123) + k * 1e-9 for i in range(n_rec) for k in range(3)]
    b_fgm = [math.pi * (i + 1) * (k + 1) for i in range(n_rec) for k in range(3)]
    quat = [0.5, -0.5, 0.5, 0.5] * n_rec
    flags = [i % 3 for i in range(n_rec)]

    cdr = w.add(struct.pack(">qiqiiiiiiiii", 312, 1, 0, 3, 6, encoding, 3, 0, 0, 0, 3, -1) + b"\x00" * 256)
    gdr = w.add(struct.pack(">qiqqqqiiiiiqiii", 84, 2, 0, 0, 0, 0, 0, 0, -1, 0, 0, 0, 0, 0, -1))
    w.patch_q(cdr + 12, gdr)

    def cpr() -> int:
        return w.add(struct.pack(">qiiiii", 28, 11, 5, 0, 1, 6))

    variables = [
        ("Timestamp", 31, [], 8, timestamps, "d"),
        ("B_NEC", 45, [3], 24, b_nec, "d"),
        ("B_FGM", 45, [3], 24, b_fgm, "d"),
        ("q_NEC_FGM", 45, [4], 32, quat, "d"),
        ("B_FLAG", 11, [], 1, flags, "B"),
    ]
    vdr_offsets = []
    prev = None
    for num, (name, dtype, dims, _rb, _vals, _code) in enumerate(variables):
        cpr_off = cpr()
        nd = len(dims)
        size = 344 + 8 * nd
        rec = struct.pack(">qiqiiqqiiiiiiiqi256si", size, 8, 0, dtype, n_rec - 1, 0, 0, 7, 0, 0, 0,
                          -1, 1, num, cpr_off, 0, name256(name), nd)
        rec += struct.pack(f">{nd}i", *dims) + struct.pack(f">{nd}i", *([-1] * nd))
        off = w.add(rec)
        vdr_offsets.append(off)
        if prev is None:
            w.patch_q(gdr + 20, off)
        else:
            w.patch_q(prev + 12, off)
        prev = off
    # uncompressed CHAR metadata variable, single VVR
    lab_off = w.add(struct.pack(">qiqiiqqiiiiiiiqi256si", 344 + 8, 8, 0, 51, 0, 0, 0, 2, 0, 0, 0, -1,
                                8, len(variables), -1, 0, name256("LABELS_BNEC"), 1)
                    + struct.pack(">i", 3) + struct.pack(">i", -1))
    w.patch_q(prev + 12, lab_off)
    labels = b"Bnorth  Beast   Bcentre "
    lab_vvr = w.add(struct.pack(">qi", 12 + len(labels), 7) + labels)
    lab_vxr = w.add(struct.pack(">qiqii", 28 + 16, 6, 0, 1, 1) + struct.pack(">iiq", 0, 0, lab_vvr))
    w.patch_q(lab_off + 28, lab_vxr)

    def leaf(values, code, first, last, rec_vals, compressed=True):
        data = struct.pack(f"{order}{(last - first + 1) * rec_vals}{code}",
                           *values[first * rec_vals:(last + 1) * rec_vals])
        if compressed:
            gz = gzip.compress(data, compresslevel=6, mtime=0)
            if truncate_cvvr:
                gz = gz[: len(gz) // 2]
            return w.add(struct.pack(">qiiq", 24 + len(gz), 13, 0, len(gz)) + gz)
        return w.add(struct.pack(">qi", 12 + len(data), 7) + data)

    def vxr(entries, n_entries=None):
        n_entries = n_entries or len(entries)
        firsts = [e[0] for e in entries] + [-1] * (n_entries - len(entries))
        lasts = [e[1] for e in entries] + [-1] * (n_entries - len(entries))
        offs = [e[2] for e in entries] + [-1] * (n_entries - len(entries))
        return w.add(struct.pack(">qiqii", 28 + 16 * n_entries, 6, 0, n_entries, len(entries))
                     + struct.pack(f">{n_entries}i", *firsts) + struct.pack(f">{n_entries}i", *lasts)
                     + struct.pack(f">{n_entries}q", *offs))

    for (name, dtype, dims, _rb, values, code), vdr in zip(variables, vdr_offsets):
        per = 1
        for d in dims:
            per *= d
        if name == "B_NEC":
            # chain: VXR#1 [0..2 CVVR, 3..5 nested VXR(3..3 VVR, 4..5 CVVR)] -> VXR#2 [6..9 or gap]
            l0 = leaf(values, code, 0, 2, per)
            l3 = leaf(values, code, 3, 3, per, compressed=False)
            l4 = leaf(values, code, 4, 5, per)
            nested = vxr([(3, 3, l3), (4, 5, l4)], n_entries=3)
            v1 = vxr([(0, 2, l0), (3, 5, nested)], n_entries=4)
            start = 7 if gap else 6
            l6 = leaf(values, code, start, 9, per)
            v2 = vxr([(start, 9, l6)])
            w.patch_q(v1 + 12, v2)
            head, tail = v1, v2
        else:
            la = leaf(values, code, 0, 4, per)
            lb = leaf(values, code, 5, 9, per)
            head = tail = vxr([(0, 4, la), (5, 9, lb)])
        w.patch_q(vdr + 28, head)
        w.patch_q(vdr + 36, tail)

    # attributes: global TITLE + License, variable-scope UNITS + FILLVAL
    def aedr(rtype, attr_num, dtype, entry_num, value_bytes, nelems):
        return w.add(struct.pack(">qiqiiiiiiiii", 56 + len(value_bytes), rtype, 0, attr_num, dtype,
                                 entry_num, nelems, 0, 0, 0, 0, 0) + value_bytes)

    attr_specs = [("TITLE", 1), ("License", 1), ("UNITS", 2), ("FILLVAL", 2)]
    prev_adr = None
    for attr_num, (name, scope) in enumerate(attr_specs):
        adr = w.add(struct.pack(">qiqqiiiiiqiii256s", 324, 4, 0, 0, scope, attr_num, 0, -1, 0, 0, 0, -1, 0,
                                name256(name)))
        if prev_adr is None:
            w.patch_q(gdr + 28, adr)
        else:
            w.patch_q(prev_adr + 12, adr)
        prev_adr = adr
        if name == "TITLE":
            text = b"GF1_OPER_FGM_ACAL_CORR_SYNTHETIC_0201"
            e = aedr(5, attr_num, 51, 0, text, len(text))
            w.patch_q(adr + 20, e)
        elif name == "License":
            text = b"Creative Commons Attribution 4.0 International (CC BY 4.0)"
            e = aedr(5, attr_num, 51, 0, text, len(text))
            w.patch_q(adr + 20, e)
        elif name == "UNITS":
            e1 = aedr(9, attr_num, 51, 1, b"nT", 2)
            e2 = aedr(9, attr_num, 51, 2, b"nT", 2)
            w.patch_q(e1 + 12, e2)
            w.patch_q(adr + 48, e1)
        else:
            e1 = aedr(9, attr_num, 45, 1, struct.pack(f"{order}d", math.nan), 1)
            e0 = aedr(9, attr_num, 31, 0, struct.pack(f"{order}d", -1e31), 1)
            w.patch_q(e1 + 12, e0)
            w.patch_q(adr + 48, e1)
    # GDR layout: size@0 type@8 rVDRhead@12 zVDRhead@20 ADRhead@28 eof@36
    # NrVars@44 NumAttr@48 rMaxRec@52 rNumDims@56 NzVars@60 UIRhead@64
    w.patch_i(gdr + 44, 0)
    w.patch_i(gdr + 48, len(attr_specs))
    w.patch_i(gdr + 60, len(variables) + 1)
    w.patch_q(gdr + 36, len(w.buf))
    image = bytes(w.buf)
    # whole-file compression
    gz = gzip.compress(image[8:], compresslevel=1, mtime=0)
    ccr_size = 32 + len(gz)
    raw = struct.pack(">II", 0xCDF30001, 0xCCCC0001)
    raw += struct.pack(">qiqqi", ccr_size, 10, 8 + ccr_size, len(image) - 8, 0) + gz
    raw += struct.pack(">qiiiii", 28, 11, 5, 0, 1, 1)
    expected = {"Timestamp": timestamps, "B_NEC": b_nec, "B_FGM": b_fgm, "q_NEC_FGM": quat, "B_FLAG": flags,
                "image": image}
    return raw, expected


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"selftest FAILED: {message}")


def run() -> None:
    raw, exp = build()
    cdf = cdf3.CDF(raw)
    check(cdf.image == exp["image"], "whole-file decompression is not byte-exact")
    check(cdf.byte_order == ">" and cdf.encoding == 1, "network encoding not detected")
    check(list(cdf.variables) == ["Timestamp", "B_NEC", "B_FGM", "q_NEC_FGM", "B_FLAG", "LABELS_BNEC"],
          f"variable chain {list(cdf.variables)}")
    for name in ("Timestamp", "B_NEC", "B_FGM", "q_NEC_FGM", "B_FLAG"):
        values, stats = cdf.read_values(name)
        check(list(values) == exp[name], f"{name} values differ")
    _, stats = cdf.read_values("B_NEC")
    check(stats["cvvr_blocks"] == 3 and stats["vvr_blocks"] == 1, f"B_NEC leaf mix {stats}")
    raw_bnec, _ = cdf.read_records("B_NEC")
    check(raw_bnec == struct.pack(">30d", *exp["B_NEC"]), "B_NEC raw big-endian bytes differ")
    labels, _ = cdf.read_records("LABELS_BNEC")
    check(labels == b"Bnorth  Beast   Bcentre ", f"labels {labels!r}")
    check(cdf.global_attributes.get("License") == ["Creative Commons Attribution 4.0 International (CC BY 4.0)"],
          "global License attribute")
    check(cdf.variables["B_NEC"].attributes.get("UNITS") == "nT", "B_NEC UNITS")
    fill = cdf.variables["B_NEC"].attributes.get("FILLVAL")
    check(isinstance(fill, float) and math.isnan(fill), "B_NEC FILLVAL NaN")
    check(cdf.variables["Timestamp"].attributes.get("FILLVAL") == -1e31, "Timestamp FILLVAL")

    raw_gap, _ = build(gap=True)
    try:
        cdf3.CDF(raw_gap).read_records("B_NEC")
    except cdf3.CDFError as exc:
        check("contiguity" in str(exc), f"gap error wording: {exc}")
    else:
        check(False, "record gap was not rejected")
    raw_trunc, _ = build(truncate_cvvr=True)
    try:
        cdf3.CDF(raw_trunc).read_records("B_NEC")
    except cdf3.CDFError:
        pass
    else:
        check(False, "truncated CVVR gzip stream was not rejected")
    try:
        cdf3.CDF(raw[: len(raw) - 1000])
    except cdf3.CDFError:
        pass
    else:
        check(False, "truncated file was not rejected")
    bad = bytearray(build()[1]["image"])
    struct.pack_into(">i", bad, 36, 99)
    try:
        cdf3.CDF(bytes(bad))
    except cdf3.CDFError:
        pass
    else:
        check(False, "unsupported encoding was not rejected")
    print("cdf3 selftest ok: whole-file gzip, VXRnext chain, nested VXR, CVVR+VVR leaves, attributes, negatives")


if __name__ == "__main__":
    run()
