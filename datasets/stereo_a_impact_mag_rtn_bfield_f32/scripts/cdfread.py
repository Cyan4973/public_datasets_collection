#!/usr/bin/env python3
"""Minimal pure-stdlib reader for uncompressed single-file NASA CDF files,
internal format v2.6/2.7 (32-bit offsets) and v3.x (64-bit offsets).

Scope is deliberately narrow: it decodes the internal records needed to pull
typed zVariable data out of STEREO IMPACT/MAG Level-1 CDFs (network/XDR
big-endian encoding, no compression, no sparse records, no rVariables). The
archive switched its writer from CDF 2.7 to CDF 3.x in late 2021 without
changing the data version, so both layouts are supported. Anything outside
that scope raises CDFError instead of guessing.

Record layouts (big-endian; O = 4-byte offset in v2, 8-byte in v3; every
record starts with RecordSize(O) RecordType(4)):
  CDR  type 1   GDRoffset(O) Version Release Encoding Flags ...
  GDR  type 2   rVDRhead(O) zVDRhead(O) ADRhead(O) eof(O) NrVars NumAttr
                rMaxRec rNumDims NzVars UIRhead(O) ...
  ADR  type 4   ADRnext(O) AgrEDRhead(O) Scope Num NgrEntries MAXgrEntry rfuA
                AzEDRhead(O) NzEntries MAXzEntry rfuE Name[64 v2 | 256 v3]
  AgrEDR 5 / AzEDR 9  AEDRnext(O) AttrNum DataType Num NumElems 5*int Value
  VXR  type 6   VXRnext(O) Nentries NusedEntries First[n] Last[n] Offset[n](O)
  VVR  type 7   raw record bytes
  zVDR type 8   VDRnext(O) DataType MaxRec VXRhead(O) VXRtail(O) Flags SRecords
                rfuB rfuC rfuF NumElems Num CPRorSPRoffset(O) BlockingFactor
                Name[64 v2 | 256 v3] zNumDims zDimSizes[] DimVarys[]
"""

from __future__ import annotations

import struct
import sys
from array import array

MAGIC_V2 = 0xCDF26002
MAGIC_V3 = 0xCDF30001
MAGIC2_UNCOMPRESSED = 0x0000FFFF

# CDF data type code -> (struct char, size, array typecode)
DATA_TYPES = {
    1: ("b", 1, "b"), 2: ("h", 2, "h"), 4: ("i", 4, "i"), 8: ("q", 8, "q"),
    11: ("B", 1, "B"), 12: ("H", 2, "H"), 14: ("I", 4, "I"),
    21: ("f", 4, "f"), 22: ("d", 8, "d"), 31: ("d", 8, "d"),
    33: ("q", 8, "q"), 41: ("b", 1, "b"), 44: ("f", 4, "f"), 45: ("d", 8, "d"),
    51: ("c", 1, None), 52: ("c", 1, None),
}

BIG_ENDIAN_ENCODINGS = {1, 2}  # NETWORK (XDR), SUN


class CDFError(ValueError):
    pass


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


class _Cursor:
    def __init__(self, data: bytes, off: int, ofmt: str):
        self.data, self.off, self.o = data, off, ofmt

    def i(self) -> int:
        v = struct.unpack_from(">i", self.data, self.off)[0]
        self.off += 4
        return v

    def p(self) -> int:  # file offset field
        v = struct.unpack_from(">" + self.o, self.data, self.off)[0]
        self.off += struct.calcsize(self.o)
        return v

    def raw(self, n: int) -> bytes:
        b = self.data[self.off: self.off + n]
        self.off += n
        return b


class ZVar:
    __slots__ = ("name", "num", "data_type", "max_rec", "vxr_head", "flags",
                 "s_records", "num_elems", "dims", "dim_varys", "offset")

    @property
    def item_size(self) -> int:
        return DATA_TYPES[self.data_type][1]

    @property
    def values_per_record(self) -> int:
        n = self.num_elems if DATA_TYPES[self.data_type][0] == "c" else 1
        for d, v in zip(self.dims, self.dim_varys):
            if v:
                n *= d
        return n

    @property
    def record_bytes(self) -> int:
        n = self.num_elems
        for d, v in zip(self.dims, self.dim_varys):
            if v:
                n *= d
        return n * self.item_size


class CDF:
    def __init__(self, data: bytes):
        self.data = data
        self.size = len(data)
        if self.size < 8 + 312:
            raise CDFError("file too small for CDF header")
        m1, m2 = struct.unpack_from(">II", data, 0)
        if m1 == MAGIC_V2:
            self.v3 = False
        elif m1 == MAGIC_V3:
            self.v3 = True
        else:
            raise CDFError(f"bad magic 0x{m1:08x}; expected CDF v2.6+ or v3")
        if m2 != MAGIC2_UNCOMPRESSED:
            raise CDFError(f"compressed or unknown CDF (magic2=0x{m2:08x})")
        self.o = "q" if self.v3 else "i"
        self.name_len = 256 if self.v3 else 64
        body = self._header(8, 1)
        c = _Cursor(data, body, self.o)
        gdr = c.p()
        ver, rel, enc, flags = c.i(), c.i(), c.i(), c.i()
        if ver != (3 if self.v3 else 2):
            raise CDFError(f"CDR version {ver} inconsistent with magic")
        if enc not in BIG_ENDIAN_ENCODINGS:
            raise CDFError(f"encoding {enc} not supported (need network/big-endian)")
        if not (flags & 2):
            raise CDFError("multi-file CDF not supported")
        self.version = (ver, rel)
        self.encoding = enc
        self.row_major = bool(flags & 1)
        self.gdr_offset = gdr
        c = _Cursor(data, self._header(gdr, 2), self.o)
        _r_head, z_head, adr_head, eof = c.p(), c.p(), c.p(), c.p()
        nr_vars, num_attr, _rmax, _rnd, nz_vars = c.i(), c.i(), c.i(), c.i(), c.i()
        if eof != self.size:
            raise CDFError(f"GDR eof {eof} != file size {self.size} (truncated?)")
        if nr_vars != 0:
            raise CDFError(f"rVariables present ({nr_vars}); not supported")
        self.eof = eof
        self.num_attr = num_attr
        self.nz_vars = nz_vars
        self.zvars: dict[str, ZVar] = {}
        self._zvars_by_num: dict[int, ZVar] = {}
        off = z_head
        seen = set()
        while off:
            if off in seen:
                raise CDFError("zVDR chain loop")
            seen.add(off)
            v, nxt = self._read_zvdr(off)
            self.zvars[v.name] = v
            self._zvars_by_num[v.num] = v
            off = nxt
        if len(self.zvars) != nz_vars:
            raise CDFError(f"zVDR chain has {len(self.zvars)} vars, GDR says {nz_vars}")
        self.global_attrs: dict[str, list] = {}
        self.var_attrs: dict[str, dict[str, object]] = {n: {} for n in self.zvars}
        self._read_attrs(adr_head)
        self.allocated_records: dict[str, int] = {}

    # -- helpers -----------------------------------------------------------
    def _rec(self, off: int) -> tuple[int, int, int]:
        """Return (RecordSize, RecordType, body offset) without type check."""
        hdr = ">" + self.o + "i"
        n = struct.calcsize(hdr)
        if off < 8 or off + n > self.size:
            raise CDFError(f"record offset {off} outside file")
        rs, rt = struct.unpack_from(hdr, self.data, off)
        if rs < n or off + rs > self.size:
            raise CDFError(f"record at {off} size {rs} overruns file")
        return rs, rt, off + n

    def _header(self, off: int, rtype: int) -> int:
        rs, rt, body = self._rec(off)
        if rt != rtype:
            raise CDFError(f"record at {off} has type {rt}, expected {rtype}")
        return body

    def _read_zvdr(self, off: int) -> tuple[ZVar, int]:
        c = _Cursor(self.data, self._header(off, 8), self.o)
        v = ZVar()
        v.offset = off
        nxt = c.p()
        v.data_type, v.max_rec = c.i(), c.i()
        v.vxr_head = c.p()
        c.p()  # VXRtail
        v.flags, v.s_records = c.i(), c.i()
        c.i(), c.i(), c.i()  # rfuB rfuC rfuF
        v.num_elems, v.num = c.i(), c.i()
        c.p()  # CPRorSPRoffset
        c.i()  # BlockingFactor
        v.name = _cstr(c.raw(self.name_len))
        ndims = c.i()
        if not 0 <= ndims <= 10:
            raise CDFError(f"zVar {v.name}: bad zNumDims {ndims}")
        v.dims = [c.i() for _ in range(ndims)]
        v.dim_varys = [c.i() != 0 for _ in range(ndims)]
        if v.data_type not in DATA_TYPES:
            raise CDFError(f"zVar {v.name}: unsupported data type {v.data_type}")
        return v, nxt

    def _decode_value(self, dtype: int, nelems: int, off: int):
        if dtype not in DATA_TYPES:
            return None
        ch, size, _ = DATA_TYPES[dtype]
        if ch == "c":
            return _cstr(self.data[off: off + nelems])
        return list(struct.unpack_from(f">{nelems}{ch}", self.data, off))

    def _read_attrs(self, adr_head: int) -> None:
        off = adr_head
        count = 0
        seen = set()
        while off:
            if off in seen:
                raise CDFError("ADR chain loop")
            seen.add(off)
            c = _Cursor(self.data, self._header(off, 4), self.o)
            nxt, agr_head = c.p(), c.p()
            scope, _num, _ngr, _maxgr, _rfa = c.i(), c.i(), c.i(), c.i(), c.i()
            az_head = c.p()
            c.i(), c.i(), c.i()
            name = _cstr(c.raw(self.name_len))
            count += 1
            for head, rtype in ((agr_head, 5), (az_head, 9)):
                e = head
                eseen = set()
                while e:
                    if e in eseen:
                        raise CDFError("AEDR chain loop")
                    eseen.add(e)
                    ec = _Cursor(self.data, self._header(e, rtype), self.o)
                    enext = ec.p()
                    _attr_num, dtype, enum, nelems = ec.i(), ec.i(), ec.i(), ec.i()
                    for _ in range(5):
                        ec.i()
                    val = self._decode_value(dtype, nelems, ec.off)
                    if scope in (1, 3):  # global
                        self.global_attrs.setdefault(name, []).append(val)
                    elif rtype == 9 and enum in self._zvars_by_num:
                        self.var_attrs[self._zvars_by_num[enum].name][name] = val
                    e = enext
            off = nxt
        if count != self.num_attr:
            raise CDFError(f"ADR chain has {count} attributes, GDR says {self.num_attr}")

    # -- data ------------------------------------------------------------
    def segments(self, name: str) -> list[tuple[int, int, int]]:
        """Return sorted (first, last, data_offset) VVR segments for a zVar.

        Walks the full VXR linked list, recursing into child VXRs, checks that
        the segments cover records 0..MaxRec contiguously without overlap, and
        clips the allocated-but-unwritten tail (a blocking factor may
        preallocate records beyond MaxRec).
        """
        v = self.zvars[name]
        if v.flags & 4:
            raise CDFError(f"zVar {name} is compressed")
        if v.s_records != 0:
            raise CDFError(f"zVar {name} uses sparse records ({v.s_records})")
        rb = v.record_bytes
        osz = struct.calcsize(self.o)
        segs: list[tuple[int, int, int]] = []
        visited: set[int] = set()

        def walk(off: int, depth: int) -> None:
            if depth > 16:
                raise CDFError("VXR tree too deep")
            while off:
                if off in visited:
                    raise CDFError("VXR loop")
                visited.add(off)
                rs, rt, body = self._rec(off)
                if rt != 6:
                    raise CDFError(f"record at {off} has type {rt}, expected VXR")
                c = _Cursor(self.data, body, self.o)
                nxt, nent, nused = c.p(), c.i(), c.i()
                if not 0 <= nused <= nent or (body - off) + osz + 8 + nent * (8 + osz) > rs:
                    raise CDFError(f"VXR at {off}: bad entry counts {nused}/{nent}")
                firsts = struct.unpack_from(f">{nent}i", self.data, c.off)
                lasts = struct.unpack_from(f">{nent}i", self.data, c.off + 4 * nent)
                offs = struct.unpack_from(f">{nent}{self.o}", self.data, c.off + 8 * nent)
                for k in range(nused):
                    first, last, child = firsts[k], lasts[k], offs[k]
                    if first < 0 or last < first:
                        raise CDFError(f"VXR at {off}: bad range {first}..{last}")
                    crs, crt, cbody = self._rec(child)
                    if crt == 7:
                        need = (cbody - child) + (last - first + 1) * rb
                        if crs < need:
                            raise CDFError(
                                f"VVR at {child}: size {crs} < needed {need} for {first}..{last}")
                        segs.append((first, last, cbody))
                    elif crt == 6:
                        walk(child, depth + 1)
                    elif crt == 13:
                        raise CDFError(f"compressed CVVR at {child}")
                    else:
                        raise CDFError(f"VXR child at {child} has record type {crt}")
                off = nxt

        walk(v.vxr_head, 0)
        segs.sort()
        expect = 0
        for first, last, _ in segs:
            if first != expect:
                raise CDFError(
                    f"zVar {name}: VVR coverage gap/overlap at record {expect} (segment starts {first})")
            expect = last + 1
        nrec = v.max_rec + 1
        if expect < nrec:
            raise CDFError(f"zVar {name}: VVRs cover {expect} records, MaxRec+1 = {nrec}")
        self.allocated_records[name] = expect
        clipped = []
        for first, last, doff in segs:
            if first >= nrec:
                break
            clipped.append((first, min(last, nrec - 1), doff))
        return clipped

    def read_chars(self, name: str) -> list[str]:
        """Return the character strings of a CDF_CHAR/UCHAR zVar (all records)."""
        v = self.zvars[name]
        if DATA_TYPES[v.data_type][0] != "c":
            raise CDFError(f"zVar {name} is not character data")
        out = []
        for first, last, doff in self.segments(name):
            for r in range(last - first + 1):
                base = doff + r * v.record_bytes
                for k in range(v.record_bytes // v.num_elems):
                    o = base + k * v.num_elems
                    out.append(_cstr(self.data[o:o + v.num_elems]))
        return out

    def read_array(self, name: str) -> array:
        """Return all records of a numeric zVar as a native-endian array."""
        v = self.zvars[name]
        ch, size, tc = DATA_TYPES[v.data_type]
        if tc is None:
            raise CDFError(f"zVar {name} is character data")
        rb = v.record_bytes
        out = array(tc)
        for first, last, doff in self.segments(name):
            out.frombytes(self.data[doff: doff + (last - first + 1) * rb])
        if sys.byteorder == "little" and size > 1:
            out.byteswap()
        if len(out) != (v.max_rec + 1) * v.values_per_record:
            raise CDFError(f"zVar {name}: decoded {len(out)} values, expected "
                           f"{(v.max_rec + 1) * v.values_per_record}")
        return out


# ---------------------------------------------------------------------------
# Synthetic writer used only by the self-test.
# ---------------------------------------------------------------------------

def write_synthetic(vars_spec: list[dict], attrs: list[dict], vxr_split: list[list[int]],
                    v3: bool = False) -> bytes:
    """Build a tiny CDF (v2.7 or v3.7 layout, network encoding, uncompressed).

    vars_spec: [{name, dtype, dims, records: bytes(big-endian), nrec,
                 num_elems (default 1), nrv (default False)}]
    attrs: [{name, scope, entries: [(varnum or None, dtype, raw_be_bytes, nelems)]}]
    vxr_split: per variable, list of VVR record counts. VVRs are written in
    reverse record order, each with 3 preallocated pad records, and indexed by
    a top VXR chain of 1-segment VXRs whose last member points at a child VXR
    holding the final two segments, exercising chain walking and recursion.
    """
    O = "q" if v3 else "i"
    OS = struct.calcsize(O)
    NL = 256 if v3 else 64
    HDR = OS + 4
    buf = bytearray()
    buf += struct.pack(">II", MAGIC_V3 if v3 else MAGIC_V2, MAGIC2_UNCOMPRESSED)

    def put(fmt, off, *vals):
        struct.pack_into(">" + fmt, buf, off, *vals)

    def rec(rtype: int, fields: list[tuple[str, object]], tail: bytes = b"") -> int:
        body = b"".join(struct.pack(">" + f, v) for f, v in fields) + tail
        o = len(buf)
        buf.extend(struct.pack(">" + O + "i", HDR + len(body), rtype) + body)
        return o

    cdr = rec(1, [(O, 0), ("i", 3 if v3 else 2), ("i", 7), ("i", 1), ("i", 3),
                  ("i", 0), ("i", 0), ("i", 0), ("i", -1), ("i", -1)], b"\x00" * 256)
    gdr = rec(2, [(O, 0), (O, 0), (O, 0), (O, 0), ("i", 0), ("i", len(attrs)), ("i", -1),
                  ("i", 0), ("i", len(vars_spec)), (O, 0), ("i", 0), ("i", -1), ("i", -1)])
    put(O, cdr + HDR, gdr)
    gb = gdr + HDR  # rVDRhead, zVDRhead, ADRhead, eof

    adr_offs = []
    for ai, a in enumerate(attrs):
        gr, zr = [], []
        for (vnum, dtype, raw, nelems) in a["entries"]:
            e = rec(9 if vnum is not None else 5,
                    [(O, 0), ("i", ai), ("i", dtype), ("i", vnum if vnum is not None else 0),
                     ("i", nelems)] + [("i", 0)] * 5, raw)
            (zr if vnum is not None else gr).append(e)
        for lst in (gr, zr):
            for x, y in zip(lst, lst[1:]):
                put(O, x + HDR, y)
        adr = rec(4, [(O, 0), (O, gr[0] if gr else 0), ("i", a["scope"]), ("i", ai),
                      ("i", len(gr)), ("i", len(gr) - 1), ("i", 0), (O, zr[0] if zr else 0),
                      ("i", len(zr)), ("i", len(zr) - 1), ("i", 0)],
                  a["name"].encode().ljust(NL, b"\x00"))
        adr_offs.append(adr)
    for x, y in zip(adr_offs, adr_offs[1:]):
        put(O, x + HDR, y)

    vdr_offs = []
    for vi, spec in enumerate(vars_spec):
        nrec = spec["nrec"]
        rb = len(spec["records"]) // nrec
        counts = vxr_split[vi]
        assert sum(counts) == nrec
        bounds, start = [], 0
        for cnt in counts:
            bounds.append((start, start + cnt - 1))
            start += cnt
        vvr_offs = {}
        for (first, last) in reversed(bounds):
            chunk = spec["records"][first * rb:(last + 1) * rb]
            o = len(buf)
            buf.extend(struct.pack(">" + O + "i", HDR + len(chunk) + 3 * rb, 7) + chunk
                       + b"\xee" * (3 * rb))
            vvr_offs[first] = o

        def emit_vxr(segs, nent, child_override=None):
            f = [s[0] for s in segs] + [-1] * (nent - len(segs))
            l = [s[1] for s in segs] + [-1] * (nent - len(segs))
            of = ([child_override] if child_override else [vvr_offs[s[0]] for s in segs]) \
                + [-1] * (nent - len(segs))
            tail = struct.pack(f">{nent}i", *f) + struct.pack(f">{nent}i", *l) \
                + struct.pack(f">{nent}{O}", *of)
            return rec(6, [(O, 0), ("i", nent), ("i", len(segs))], tail)

        top_segs = bounds[:-2] if len(bounds) > 2 else bounds[:1]
        child_segs = bounds[len(top_segs):]
        chain = [emit_vxr([s], 2) for s in top_segs]
        if child_segs:
            child = emit_vxr(child_segs, len(child_segs) + 1)
            chain.append(emit_vxr([(child_segs[0][0], child_segs[-1][1])], 1, child))
        for x, y in zip(chain, chain[1:]):
            put(O, x + HDR, y)
        ndims = len(spec["dims"])
        tail = spec["name"].encode().ljust(NL, b"\x00") + struct.pack(">i", ndims) \
            + struct.pack(f">{ndims}i", *spec["dims"]) + struct.pack(f">{ndims}i", *([-1] * ndims))
        vdr = rec(8, [(O, 0), ("i", spec["dtype"]), ("i", nrec - 1), (O, chain[0]),
                      (O, chain[-1]), ("i", 0 if spec.get("nrv") else 1), ("i", 0),
                      ("i", 0), ("i", 0), ("i", -1), ("i", spec.get("num_elems", 1)),
                      ("i", vi), (O, -1), ("i", 0)], tail)
        vdr_offs.append(vdr)
    for x, y in zip(vdr_offs, vdr_offs[1:]):
        put(O, x + HDR, y)
    put(O, gb + OS, vdr_offs[0] if vdr_offs else 0)
    put(O, gb + 2 * OS, adr_offs[0] if adr_offs else 0)
    put(O, gb + 3 * OS, len(buf))
    return bytes(buf)
