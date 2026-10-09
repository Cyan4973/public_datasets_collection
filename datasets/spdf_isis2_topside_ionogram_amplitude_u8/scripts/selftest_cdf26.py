#!/usr/bin/env python3
"""Self-test for cdf26.py and the isis2_ionogram decision rule on synthetic
CDF v2.6 files written from scratch here (no network, no real data).

Covers: CDR/GDR/zVDR chain, nested VXR, several GZIP CVVRs, a plain VVR inside
a compressed variable, uncompressed scalar VVRs, AzEDR attributes, the
trailing zero-record trim, and negative cases (truncation, record gap, bad
gzip, decompressed-length mismatch, wrong data type).
"""

import gzip
import os
import random
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdf26  # noqa: E402
import isis2_ionogram as iono  # noqa: E402


def i32(*v):
    return struct.pack(">%di" % len(v), *v)


class Writer:
    """Write a single-file, uncompressed-file CDF v2.6 with zVariables only."""

    def __init__(self):
        self.buf = bytearray(struct.pack(">II", 0xCDF26002, 0x0000FFFF))

    def add(self, rec):
        off = len(self.buf)
        self.buf += rec
        return off

    def patch(self, off, value):
        struct.pack_into(">i", self.buf, off, value)

    def build(self, variables, attrs):
        cdr = self.add(i32(304, 1, 0, 2, 6, 1, 3, 0, 0, 0, -1, -1) + b"\0" * 256)
        gdr = self.add(i32(60, 2, 0, 0, 0, 0, 0, len(attrs), -1, 0, len(variables), 0, 0, 0, 0))
        self.patch(cdr + 8, gdr)
        prev_vdr = None
        vdr_offsets = []
        for num, v in enumerate(variables):
            nd = len(v["dims"])
            body = i32(0, 8, 0, v["type"], len(v["records"]) - 1, 0, 0, v["flags"], 0, 0, -1, -1,
                       1, num, -1, v.get("blocking", 0))
            body += v["name"].encode().ljust(64, b"\0") + i32(nd, *v["dims"]) + i32(*([-1] * nd))
            if v["flags"] & 2:
                body += v["pad"]
            body = i32(len(body)) + body[4:]
            off = self.add(body)
            vdr_offsets.append(off)
            if prev_vdr is None:
                self.patch(gdr + 12, off)
            else:
                self.patch(prev_vdr + 8, off)
            prev_vdr = off
            if v.get("compress"):
                cpr = self.add(i32(24, 11, 5, 0, 1, 6))
                self.patch(off + 56, cpr)
            # data blocks
            blocks = []
            recs = v["records"]
            for first, last, kind in v["plan"]:
                payload = b"".join(recs[first:last + 1])
                if kind == "cvvr":
                    comp = gzip.compress(payload, compresslevel=6)
                    boff = self.add(i32(16 + len(comp), 13, 0, len(comp)) + comp)
                else:
                    boff = self.add(i32(8 + len(payload), 7) + payload)
                blocks.append((first, last, boff))
            # VXR tree: optionally nest the first `nest` blocks in a child VXR
            nest = v.get("nest", 0)

            def vxr(entries, spare=1):
                n = len(entries) + spare
                firsts = [e[0] for e in entries] + [-1] * spare
                lasts = [e[1] for e in entries] + [-1] * spare
                offs = [e[2] for e in entries] + [-1] * spare
                return self.add(i32(20 + 12 * n, 6, 0, n, len(entries), *firsts, *lasts, *offs))

            if nest:
                child = vxr(blocks[:nest])
                top_entries = [(blocks[0][0], blocks[nest - 1][1], child)] + blocks[nest:]
            else:
                top_entries = blocks
            if v.get("split_top") and len(top_entries) > 1:
                head = vxr(top_entries[:1], spare=0)
                tail = vxr(top_entries[1:], spare=0)
                self.patch(head + 8, tail)
            else:
                head = vxr(top_entries)
            self.patch(off + 20, head)
        # attributes: one variable-scope attribute per name, AzEDR entries
        prev_adr = None
        for anum, (aname, entries) in enumerate(attrs):
            adr = self.add(i32(116, 4, 0, 0, 2, anum, 0, -1, 0, 0, len(entries), -1, 0)
                           + aname.encode().ljust(64, b"\0"))
            if prev_adr is None:
                self.patch(gdr + 16, adr)
            else:
                self.patch(prev_adr + 8, adr)
            prev_adr = adr
            prev_e = None
            for varnum, dtype, value in entries:
                ne = len(value) // cdf26.CDF_TYPES[dtype][1]
                e = self.add(i32(48 + len(value), 9, 0, anum, dtype, varnum, ne, 0, 0, 0, -1, -1) + value)
                if prev_e is None:
                    self.patch(adr + 36, e)
                else:
                    self.patch(prev_e + 8, e)
                prev_e = e
        self.patch(gdr + 20, len(self.buf))
        return bytes(self.buf)


def scalar(name, dtype, value, fmt):
    return {"name": name, "type": dtype, "dims": [], "flags": 4, "compress": True,
            "records": [struct.pack(">" + fmt, value)], "plan": [(0, 0, "vvr")]}


def make_ionogram(rows, trailer=0, rng=None, sweep_top=10.0, ampl_type=11):
    rng = rng or random.Random(1)
    n = rows + trailer
    ampl = [bytes(rng.randrange(256) for _ in range(223)) for _ in range(rows)] + [b"\0" * 223] * trailer
    t0 = 62316185859688.0
    epoch = [struct.pack(">d", t0 + 22.2 * i) for i in range(rows)] + [struct.pack(">d", t0)] * trailer
    fixed = 147
    fr = [0.25] * fixed + [0.1 + (sweep_top - 0.1) * i / (rows - fixed - 1) for i in range(rows - fixed)]
    freq = [struct.pack(">d", x) for x in fr] + [struct.pack(">d", 0.0)] * trailer
    third, cut = n // 3, (2 * n) // 3
    variables = [
        scalar("vh_num", 4, rows, "i"),
        scalar("f_num", 4, 223, "i"),
        scalar("year", 4, 74, "i"),
        {"name": "Epoch", "type": 31, "dims": [], "flags": 1, "records": epoch,
         "plan": [(0, n - 1, "vvr")], "split_top": False},
        {"name": "ampl", "type": ampl_type, "dims": [223], "flags": 5, "compress": True, "blocking": 1000,
         "records": ampl, "plan": [(0, third - 1, "cvvr"), (third, cut - 1, "cvvr"), (cut, n - 1, "vvr")],
         "nest": 2, "split_top": True},
        {"name": "freq", "type": 45, "dims": [], "flags": 5, "compress": True, "records": freq,
         "plan": [(0, n - 1, "cvvr")]},
    ]
    attrs = [
        ("FILLVAL", [(4, 4, i32(-128))]),
        ("VALIDMIN", [(4, 4, i32(0))]),
        ("VALIDMAX", [(4, 4, i32(255))]),
    ]
    return Writer().build(variables, attrs), b"".join(ampl[:rows]), fr


def expect_error(label, data, fn):
    try:
        fn(cdf26.CDF(data))
    except (cdf26.CDFError, struct.error, IndexError) as exc:
        print(f"  ok negative[{label}]: {exc}")
        return
    raise SystemExit(f"negative test {label} did not raise")


def main():
    rng = random.Random(20261009)
    tmp = tempfile.mkdtemp(prefix="cdf26_selftest_")

    # 1) plain decode, structure, attributes
    data, ampl, fr = make_ionogram(800, 0, rng)
    c = cdf26.CDF(data)
    raw, n = c.read_raw("ampl")
    assert n == 800 and raw == ampl, "ampl round trip failed"
    assert c.read_values("vh_num") == [800]
    assert c.read_values("freq") == fr
    assert c.zattr_value("FILLVAL", "ampl") == -128
    assert c.zattr_value("VALIDMAX", "ampl") == 255
    iono.check_structure(c)
    print("  ok decode: nested VXR + 2 GZIP CVVRs + VVR in compressed var, 800x223 bytes exact")

    # 2) decision rule: kept with trailing artifact trimmed
    for trailer in (0, 1, 2):
        data, ampl, fr = make_ionogram(640, trailer, rng)
        p = os.path.join(tmp, f"t{trailer}.cdf")
        with open(p, "wb") as fh:
            fh.write(data)
        info = iono.decode(p)
        assert info["keep"], info["reason"]
        assert info["ampl"] == ampl and info["rows"] == 640 and info["trimmed_trailer"] == trailer
        assert info["freq"] == fr
    print("  ok rule: complete sweep kept; 1-2 zero trailer records trimmed exactly")

    # 3) decision rule drops
    cases = [("short", make_ionogram(300, 0, rng)[0], "row_count_out_of_range"),
             ("truncated sweep", make_ionogram(640, 0, rng, sweep_top=3.0)[0], "sweep_truncated")]
    for label, d, want in cases:
        p = os.path.join(tmp, "drop.cdf")
        with open(p, "wb") as fh:
            fh.write(d)
        info = iono.decode(p)
        assert not info["keep"] and info["reason"] == want, (label, info["reason"])
        print(f"  ok rule drop[{label}]: {want}")
    # non-zero trailer: flip the last byte of the ampl VVR (located through the
    # decoder's own VXR walk) so the trailing record is no longer all zero.
    data, _, _ = make_ionogram(640, 1, rng)
    bad = bytearray(data)
    c = cdf26.CDF(data)
    entries = []
    c._collect_entries(c.zvars["ampl"].vxr_head, entries)
    first, last, off, rt = max(entries)
    assert rt == 7
    end = off + 8 + (last - first + 1) * 223
    bad[end - 1] = 7
    p = os.path.join(tmp, "drop2.cdf")
    with open(p, "wb") as fh:
        fh.write(bytes(bad))
    info = iono.decode(p)
    assert not info["keep"] and info["reason"] == "trailing_records_not_zero_artifact"
    print("  ok rule drop[nonzero trailer]: trailing_records_not_zero_artifact")

    # 4) negative structural cases
    data, _, _ = make_ionogram(800, 0, rng)
    expect_error("truncated", data[:-100], lambda c: None)
    c = cdf26.CDF(data)
    entries = []
    c._collect_entries(c.zvars["ampl"].vxr_head, entries)
    entries.sort()
    # record gap: bump the 'First' of the second CVVR inside the nested VXR
    b = bytearray(data)
    top = c.zvars["ampl"].vxr_head
    child_off = cdf26._i32(data, top + 20 + 8 * 1)[0]  # top VXR has 1 entry (split_top)
    nent = cdf26._i32(data, child_off + 12)[0]
    first1 = cdf26._i32(data, child_off + 20 + 4 * 1)[0]
    struct.pack_into(">i", b, child_off + 20 + 4 * 1, first1 + 1)  # open a one-record gap
    expect_error("record gap", bytes(b), lambda c: c.read_raw("ampl"))
    # corrupt gzip payload of the first CVVR
    b = bytearray(data)
    cv = entries[0][2]
    b[cv + 16 + 20] ^= 0xFF
    b[cv + 16 + 21] ^= 0xFF
    expect_error("bad gzip", bytes(b), lambda c: c.read_raw("ampl"))
    # decompressed length mismatch: claim more records in the first CVVR entry
    b = bytearray(data)
    last0 = cdf26._i32(data, child_off + 20 + 4 * nent)[0]
    struct.pack_into(">i", b, child_off + 20 + 4 * nent, last0 + 1)  # claim one more record
    expect_error("length mismatch", bytes(b), lambda c: c.read_raw("ampl"))
    # wrong data type for ampl
    data2, _, _ = make_ionogram(640, 0, rng, ampl_type=1)
    expect_error("ampl type", data2, iono.check_structure)
    print("cdf26 self-test passed")


if __name__ == "__main__":
    main()
