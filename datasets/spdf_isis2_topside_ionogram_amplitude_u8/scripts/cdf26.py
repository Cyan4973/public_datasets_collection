"""Minimal pure-stdlib reader for single-file CDF v2.6 (big-endian network
encoding, 4-byte offsets), sufficient for the ISIS-2 SFS digitized ionogram
CDFs on the SPDF/CDAWeb archive.

Structure walked (CDF Internal Format Description, v2.x layout):
  magic1 0xCDF26002, magic2 0x0000FFFF (uncompressed file)
  CDR (type 1) -> GDR (type 2) -> zVDR chain (type 8)
  zVDR -> VXR chain (type 6, nested VXRs allowed)
       -> VVR (type 7, uncompressed) or CVVR (type 13, compressed)
  zVDR.CPRorSPRoffset -> CPR (type 11) giving the compression type
  ADR (type 4) -> AzEDR (type 9) entries for variable attributes.

Only GZIP (cType 5) and NONE are accepted; anything else is a hard error.
Every structural field is checked; a record range not covered by the VXR tree
(i.e. a virtual / pad record) is a hard error rather than silently padded.
"""

import struct
import zlib

MAGIC1_V26 = 0xCDF26002
MAGIC2_UNCOMPRESSED = 0x0000FFFF

CDF_TYPES = {
    1: ("b", 1), 2: ("h", 2), 4: ("i", 4), 8: ("q", 8),
    11: ("B", 1), 12: ("H", 2), 14: ("I", 4),
    21: ("f", 4), 22: ("d", 8), 31: ("d", 8), 41: ("b", 1),
    44: ("f", 4), 45: ("d", 8), 51: ("s", 1), 52: ("s", 1),
}


class CDFError(ValueError):
    pass


def _i32(buf, off, n=1):
    if off < 0 or off + 4 * n > len(buf):
        raise CDFError(f"read past end at offset {off}")
    return struct.unpack_from(">%di" % n, buf, off)


class ZVar:
    __slots__ = ("name", "num", "data_type", "max_rec", "vxr_head", "flags",
                 "s_records", "num_elems", "cpr_offset", "blocking",
                 "dims", "dim_varys", "pad_value", "offset")


class CDF:
    def __init__(self, data):
        self.data = data
        if len(data) < 8 + 4 * 12:
            raise CDFError("file too short")
        m1, m2 = struct.unpack_from(">II", data, 0)
        if m1 != MAGIC1_V26:
            raise CDFError(f"unexpected magic1 {m1:#010x}")
        if m2 != MAGIC2_UNCOMPRESSED:
            raise CDFError(f"unexpected magic2 {m2:#010x} (compressed-file CDFs unsupported)")
        rs, rt, gdr, ver, rel, enc, flags = _i32(data, 8, 7)
        if rt != 1:
            raise CDFError(f"CDR record type {rt}")
        if (ver, rel) != (2, 6):
            raise CDFError(f"CDF version {ver}.{rel} unsupported")
        if enc != 1:
            raise CDFError(f"encoding {enc} is not network (big-endian)")
        if not flags & 2:
            raise CDFError("CDR flags: not a single-file CDF")
        self.version = (ver, rel)
        g = _i32(data, gdr, 12)
        if g[1] != 2:
            raise CDFError(f"GDR record type {g[1]}")
        _, _, rvdr, zvdr, adr, eof, nr, na, rmax, rnd, nz, uir = g
        if eof != len(data):
            raise CDFError(f"GDR eof {eof} != file length {len(data)} (truncated?)")
        if nr != 0:
            raise CDFError(f"unexpected rVariables: {nr}")
        self.adr_head = adr
        self.num_attr = na
        self.zvars = {}
        self.zvars_by_num = {}
        off = zvdr
        seen = 0
        while off:
            v = self._read_zvdr(off)
            if v.name in self.zvars:
                raise CDFError(f"duplicate zVariable {v.name}")
            self.zvars[v.name] = v
            self.zvars_by_num[v.num] = v
            off = self._next
            seen += 1
            if seen > nz:
                raise CDFError("zVDR chain longer than GDR NzVars")
        if seen != nz:
            raise CDFError(f"zVDR chain has {seen} entries, GDR says {nz}")

    def _read_zvdr(self, off):
        d = self.data
        f = _i32(d, off, 16)
        rs, rt, nxt, dt, maxrec, vxh, vxt, flags, srec, _, _, _, ne, num, cpr, bf = f
        if rt != 8:
            raise CDFError(f"zVDR record type {rt} at {off}")
        v = ZVar()
        v.offset = off
        v.name = d[off + 64:off + 128].split(b"\0", 1)[0].decode("ascii")
        nd = _i32(d, off + 128)[0]
        if not 0 <= nd <= 10:
            raise CDFError(f"bad zNumDims {nd} for {v.name}")
        v.dims = _i32(d, off + 132, nd) if nd else ()
        v.dim_varys = _i32(d, off + 132 + 4 * nd, nd) if nd else ()
        v.data_type, v.max_rec, v.vxr_head, v.flags = dt, maxrec, vxh, flags
        v.s_records, v.num_elems, v.num, v.cpr_offset, v.blocking = srec, ne, num, cpr, bf
        v.pad_value = None
        if flags & 2:
            if dt not in CDF_TYPES:
                raise CDFError(f"unknown data type {dt}")
            size = CDF_TYPES[dt][1] * ne
            p = off + 132 + 8 * nd
            v.pad_value = d[p:p + size]
        self._next = nxt
        return v

    def record_size(self, v):
        if v.data_type not in CDF_TYPES:
            raise CDFError(f"unknown data type {v.data_type}")
        n = CDF_TYPES[v.data_type][1] * v.num_elems
        for size, vary in zip(v.dims, v.dim_varys):
            if vary:
                n *= size
        return n

    def compression(self, v):
        if not v.flags & 4:
            return 0
        f = _i32(self.data, v.cpr_offset, 5)
        rs, rt, ctype, _, pcount = f
        if rt != 11:
            raise CDFError(f"CPR record type {rt} for {v.name}")
        return ctype

    def _collect_entries(self, vxr_off, out, depth=0):
        d = self.data
        if depth > 8:
            raise CDFError("VXR nesting too deep")
        guard = 0
        while vxr_off:
            rs, rt, nxt, nent, nused = _i32(d, vxr_off, 5)
            if rt != 6:
                raise CDFError(f"VXR record type {rt} at {vxr_off}")
            if not 0 <= nused <= nent:
                raise CDFError("VXR NusedEntries out of range")
            first = _i32(d, vxr_off + 20, nent) if nent else ()
            last = _i32(d, vxr_off + 20 + 4 * nent, nent) if nent else ()
            offs = _i32(d, vxr_off + 20 + 8 * nent, nent) if nent else ()
            for i in range(nused):
                sub_rt = _i32(d, offs[i] + 4)[0]
                if sub_rt == 6:
                    self._collect_entries(offs[i], out, depth + 1)
                elif sub_rt in (7, 13):
                    out.append((first[i], last[i], offs[i], sub_rt))
                else:
                    raise CDFError(f"VXR entry points to record type {sub_rt}")
            vxr_off = nxt
            guard += 1
            if guard > 100000:
                raise CDFError("VXR chain loop")

    def read_raw(self, name):
        """Return (bytes, n_records) of all records of a zVariable, in record
        order, as stored (big-endian elements). Requires full coverage."""
        v = self.zvars.get(name)
        if v is None:
            raise CDFError(f"no zVariable {name!r}")
        d = self.data
        rsize = self.record_size(v)
        nrec = v.max_rec + 1
        if nrec <= 0:
            return b"", 0
        ctype = self.compression(v)
        if ctype not in (0, 5):
            raise CDFError(f"unsupported compression type {ctype} for {name}")
        entries = []
        self._collect_entries(v.vxr_head, entries)
        entries.sort()
        parts = []
        expect = 0
        for first, last, off, rt in entries:
            if first != expect:
                raise CDFError(f"{name}: record gap/overlap at {expect} (entry starts {first})")
            if last < first:
                raise CDFError(f"{name}: inverted VXR entry")
            want = (last - first + 1) * rsize
            rs = _i32(d, off)[0]
            if rt == 7:
                # The CDF library stores a plain VVR even for a compressed
                # variable when compressing the block would not shrink it.
                chunk = d[off + 8:off + 8 + want]
                if rs - 8 < want or len(chunk) != want:
                    raise CDFError(f"{name}: VVR too short")
            else:
                if ctype != 5:
                    raise CDFError(f"{name}: CVVR without GZIP CPR")
                _, _, _, csize = _i32(d, off, 4)
                if csize <= 0 or off + 16 + csize > len(d) or csize > rs - 16:
                    raise CDFError(f"{name}: bad CVVR cSize {csize}")
                comp = d[off + 16:off + 16 + csize]
                dec = zlib.decompressobj(31)
                try:
                    chunk = dec.decompress(comp)
                    chunk += dec.flush()
                except zlib.error as exc:
                    raise CDFError(f"{name}: corrupt gzip stream in CVVR: {exc}") from exc
                if not dec.eof:
                    raise CDFError(f"{name}: truncated gzip stream in CVVR")
                if dec.unused_data.strip(b"\0"):
                    raise CDFError(f"{name}: trailing data after gzip stream")
                if len(chunk) != want:
                    raise CDFError(f"{name}: CVVR decompressed to {len(chunk)} bytes, expected {want}")
            parts.append(chunk)
            expect = last + 1
        if expect != nrec:
            raise CDFError(f"{name}: VXR covers {expect} records, MaxRec+1 = {nrec}")
        out = b"".join(parts)
        if len(out) != nrec * rsize:
            raise CDFError(f"{name}: assembled {len(out)} bytes, expected {nrec * rsize}")
        return out, nrec

    def read_values(self, name):
        v = self.zvars[name]
        raw, nrec = self.read_raw(name)
        code, size = CDF_TYPES[v.data_type]
        if code == "s":
            return raw
        n = len(raw) // size
        return list(struct.unpack(">%d%s" % (n, code), raw))

    def zattr(self, attr_name, var_name):
        """Return (data_type, raw_value_bytes) of a variable-scope attribute
        entry for zVariable var_name, or None."""
        v = self.zvars[var_name]
        d = self.data
        off = self.adr_head
        guard = 0
        while off:
            f = _i32(d, off, 13)
            rs, rt, nxt, agr, scope, num, ngr, maxgr, _, az, nze, maxz, _ = f
            if rt != 4:
                raise CDFError(f"ADR record type {rt}")
            name = d[off + 52:off + 116].split(b"\0", 1)[0].decode("ascii")
            if name == attr_name:
                e = az
                while e:
                    ers, ert, enext, anum, dt, enum, nelem = _i32(d, e, 7)
                    if ert != 9:
                        raise CDFError(f"AzEDR record type {ert}")
                    if enum == v.num:
                        size = CDF_TYPES[dt][1] * nelem
                        return dt, d[e + 48:e + 48 + size]
                    e = enext
                return None
            off = nxt
            guard += 1
            if guard > self.num_attr + 1:
                raise CDFError("ADR chain loop")
        return None

    def zattr_value(self, attr_name, var_name):
        r = self.zattr(attr_name, var_name)
        if r is None:
            return None
        dt, raw = r
        code, size = CDF_TYPES[dt]
        if code == "s":
            return raw.decode("ascii", "replace")
        vals = struct.unpack(">%d%s" % (len(raw) // size, code), raw)
        return vals[0] if len(vals) == 1 else list(vals)
