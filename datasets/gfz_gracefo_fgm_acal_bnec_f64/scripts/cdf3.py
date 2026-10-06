#!/usr/bin/env python3
"""Minimal pure-stdlib reader for NASA CDF version 3 files.

Scope is exactly what the GFZ GRACE-FO FGM ACAL_CORR v0201 daily files use:

* optional whole-file compression (magic ``CDF30001 CCCC0001``: CCR record at
  byte 8, CPR with GZIP compression type 5); the compressed body starts at
  byte 40 and decompresses to the CDF image without its 8 magic bytes;
* CDR, GDR, ADR/AzEDR/AgrEDR attribute chains, zVDR chain;
* variable data reached through the VXR chain (``VXRnext`` links and nested
  VXRs), whose entries point at VVRs (raw records) or CVVRs (one GZIP stream
  per CVVR, per-variable CPR with compression type 5).

All internal record fields are big-endian.  Data values follow the CDR
encoding; only encoding 1 (network, big-endian) and the little-endian
encodings 4/6/13 are accepted.  Anything outside this scope raises
``CDFError`` instead of being guessed.  Reference: CDF Internal Format
Description, CDF version 3.x (NASA GSFC SPDF).
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

CDF_MAGIC_V3 = 0xCDF30001
MAGIC_UNCOMPRESSED = 0x0000FFFF
MAGIC_COMPRESSED = 0xCCCC0001

CDR, GDR, RVDR, ADR, AGREDR, VXR, VVR, ZVDR, AZEDR, CCR, CPR, SPR, CVVR = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
)
GZIP_CTYPE = 5

# CDF data type -> (struct code, element size)
DATA_TYPES = {
    1: ("b", 1),    # CDF_INT1
    2: ("h", 2),    # CDF_INT2
    4: ("i", 4),    # CDF_INT4
    8: ("q", 8),    # CDF_INT8
    11: ("B", 1),   # CDF_UINT1
    12: ("H", 2),   # CDF_UINT2
    14: ("I", 4),   # CDF_UINT4
    21: ("f", 4),   # CDF_REAL4
    22: ("d", 8),   # CDF_REAL8
    31: ("d", 8),   # CDF_EPOCH (milliseconds since 0000-01-01T00:00:00)
    33: ("q", 8),   # CDF_TIME_TT2000
    41: ("b", 1),   # CDF_BYTE
    44: ("f", 4),   # CDF_FLOAT
    45: ("d", 8),   # CDF_DOUBLE
    51: ("s", 1),   # CDF_CHAR
    52: ("s", 1),   # CDF_UCHAR
}
BIG_ENDIAN_ENCODINGS = {1, 2, 5, 7, 9, 12}   # network, SUN, SGi, IBMRS, MAC, PPC
LITTLE_ENDIAN_ENCODINGS = {4, 6, 13}          # DECSTATION, IBMPC, ALPHAVMSi


class CDFError(ValueError):
    pass


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="strict").rstrip()


def _gunzip_exact(payload: bytes, expected: int | None, what: str) -> bytes:
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = decoder.decompress(payload) + decoder.flush()
    except zlib.error as exc:
        raise CDFError(f"{what}: gzip stream does not decode: {exc}") from exc
    if not decoder.eof:
        raise CDFError(f"{what}: gzip stream is truncated")
    if decoder.unused_data.strip(b"\x00"):
        raise CDFError(f"{what}: {len(decoder.unused_data)} unexpected bytes after gzip stream")
    if expected is not None and len(out) != expected:
        raise CDFError(f"{what}: decompressed {len(out)} bytes, expected {expected}")
    return out


def decompress_whole_file(raw: bytes) -> tuple[bytes, dict]:
    """Return the uncompressed CDF image (with uncompressed magic) and facts."""
    if len(raw) < 48:
        raise CDFError("file too short for a CDF")
    magic1, magic2 = struct.unpack_from(">II", raw, 0)
    if magic1 != CDF_MAGIC_V3:
        raise CDFError(f"not a CDF v3 file (magic {magic1:#010x})")
    if magic2 == MAGIC_UNCOMPRESSED:
        return raw, {"whole_file_compression": None}
    if magic2 != MAGIC_COMPRESSED:
        raise CDFError(f"unknown second magic {magic2:#010x}")
    ccr_size, ccr_type, cpr_offset, usize, _rfu = struct.unpack_from(">qiqqi", raw, 8)
    if ccr_type != CCR:
        raise CDFError(f"expected CCR at byte 8, found record type {ccr_type}")
    if not 8 + 32 < 8 + ccr_size <= len(raw):
        raise CDFError("CCR size out of range")
    cpr_size, cpr_type, ctype, _rfua, pcount = struct.unpack_from(">qiiii", raw, cpr_offset)
    if cpr_type != CPR:
        raise CDFError(f"expected CPR at {cpr_offset}, found record type {cpr_type}")
    params = list(struct.unpack_from(f">{pcount}i", raw, cpr_offset + 24))
    if ctype != GZIP_CTYPE:
        raise CDFError(f"whole-file compression type {ctype} is not GZIP")
    if cpr_offset + cpr_size != len(raw):
        raise CDFError("CPR is not the final record of the compressed file")
    body = _gunzip_exact(raw[40 : 8 + ccr_size], usize, "whole-file CCR")
    image = struct.pack(">II", CDF_MAGIC_V3, MAGIC_UNCOMPRESSED) + body
    return image, {"whole_file_compression": "gzip", "gzip_params": params, "uncompressed_size": len(image)}


@dataclass
class Variable:
    name: str
    num: int
    data_type: int
    max_rec: int
    flags: int
    num_elems: int
    dims: list[int]
    dim_varys: list[int]
    vxr_head: int
    cpr_offset: int
    sparse_records: int
    attributes: dict = field(default_factory=dict)

    @property
    def record_varies(self) -> bool:
        return bool(self.flags & 1)

    @property
    def compressed(self) -> bool:
        return bool(self.flags & 4)

    @property
    def values_per_record(self) -> int:
        """Typed elements per record (characters count individually)."""
        count = self.num_elems
        for size, varies in zip(self.dims, self.dim_varys):
            if varies:
                count *= size
        return count

    @property
    def record_bytes(self) -> int:
        return self.values_per_record * DATA_TYPES[self.data_type][1]


class CDF:
    def __init__(self, raw: bytes):
        self.image, self.container = decompress_whole_file(raw)
        self._parse_header()

    # -- record helpers -------------------------------------------------
    def _record(self, offset: int, expected_type: int | tuple[int, ...]) -> tuple[int, int]:
        if not 8 <= offset <= len(self.image) - 12:
            raise CDFError(f"record offset {offset} outside the CDF image")
        size, rtype = struct.unpack_from(">qi", self.image, offset)
        allowed = expected_type if isinstance(expected_type, tuple) else (expected_type,)
        if rtype not in allowed:
            raise CDFError(f"record at {offset}: type {rtype}, expected {allowed}")
        if size < 12 or offset + size > len(self.image):
            raise CDFError(f"record at {offset}: size {size} out of range")
        return size, rtype

    def _parse_header(self) -> None:
        img = self.image
        self._record(8, CDR)
        (_, _, gdr_offset, version, release, encoding, flags, _ra, _rb, increment,
         _ident, _re) = struct.unpack_from(">qiqiiiiiiiii", img, 8)
        if version != 3:
            raise CDFError(f"CDF version {version} is not 3")
        if encoding in BIG_ENDIAN_ENCODINGS:
            self.byte_order = ">"
        elif encoding in LITTLE_ENDIAN_ENCODINGS:
            self.byte_order = "<"
        else:
            raise CDFError(f"unsupported CDF data encoding {encoding}")
        self.version = (version, release, increment)
        self.encoding = encoding
        self.cdr_flags = flags
        self.row_major = bool(flags & 1)
        self._record(gdr_offset, GDR)
        (_, _, rvdr_head, zvdr_head, adr_head, eof, nr_vars, num_attr, _rmax, r_dims,
         nz_vars, _uir, _rc, _leap, _re2) = struct.unpack_from(">qiqqqqiiiiiqiii", img, gdr_offset)
        if eof > len(img):
            raise CDFError(f"GDR eof {eof} beyond image length {len(img)}")
        if nr_vars:
            raise CDFError(f"{nr_vars} rVariables present; only zVariables are supported")
        self.eof = eof
        self.variables: dict[str, Variable] = {}
        by_num: dict[int, Variable] = {}
        offset = zvdr_head
        seen = set()
        while offset:
            if offset in seen:
                raise CDFError("zVDR chain loops")
            seen.add(offset)
            self._record(offset, ZVDR)
            (_, _, vdr_next, dtype, max_rec, vxr_head, _vxr_tail, vflags, srecords, _rb2,
             _rc2, _rf, num_elems, num, cpr_off, _bf, name_raw, ndims) = struct.unpack_from(
                ">qiqiiqqiiiiiiiqi256si", img, offset)
            dims = list(struct.unpack_from(f">{ndims}i", img, offset + 344))
            varys = list(struct.unpack_from(f">{ndims}i", img, offset + 344 + 4 * ndims))
            if dtype not in DATA_TYPES:
                raise CDFError(f"variable at {offset}: unsupported data type {dtype}")
            var = Variable(_cstr(name_raw), num, dtype, max_rec, vflags, num_elems, dims,
                           varys, vxr_head, cpr_off, srecords)
            if var.name in self.variables:
                raise CDFError(f"duplicate variable name {var.name}")
            self.variables[var.name] = var
            by_num[num] = var
            offset = vdr_next
        if len(self.variables) != nz_vars:
            raise CDFError(f"zVDR chain has {len(self.variables)} variables, GDR says {nz_vars}")
        self.global_attributes: dict[str, list] = {}
        offset = adr_head
        seen = set()
        count = 0
        while offset:
            if offset in seen:
                raise CDFError("ADR chain loops")
            seen.add(offset)
            self._record(offset, ADR)
            (_, _, adr_next, agr_head, scope, _num, _ngr, _maxgr, _ra3, az_head, _nz, _maxz,
             _re3, name_raw) = struct.unpack_from(">qiqqiiiiiqiii256s", img, offset)
            name = _cstr(name_raw)
            if scope in (1, 3):  # global
                self.global_attributes[name] = [v for _n, v in self._entries(agr_head, AGREDR)]
            else:  # variable scope: entry number is the variable number
                for entry_num, value in self._entries(agr_head, AGREDR):
                    raise CDFError(f"rVariable attribute entry {name}[{entry_num}] unsupported")
                for entry_num, value in self._entries(az_head, AZEDR):
                    if entry_num not in by_num:
                        raise CDFError(f"attribute {name} refers to unknown zVariable {entry_num}")
                    by_num[entry_num].attributes[name] = value
            offset = adr_next
            count += 1
        if count != num_attr:
            raise CDFError(f"ADR chain has {count} attributes, GDR says {num_attr}")

    def _entries(self, head: int, rtype: int):
        offset = head
        seen = set()
        while offset:
            if offset in seen:
                raise CDFError("AEDR chain loops")
            seen.add(offset)
            size, _ = self._record(offset, rtype)
            (_, _, nxt, _attr_num, dtype, num, num_elems, _ns, _b, _c, _d, _e) = struct.unpack_from(
                ">qiqiiiiiiiii", self.image, offset)
            if dtype not in DATA_TYPES:
                raise CDFError(f"attribute entry at {offset}: unsupported type {dtype}")
            code, width = DATA_TYPES[dtype]
            start = offset + 56
            if code == "s":
                value = _cstr(self.image[start : start + num_elems])
            else:
                end = start + width * num_elems
                if end > offset + size:
                    raise CDFError(f"attribute entry at {offset} overruns its record")
                values = struct.unpack_from(f"{self.byte_order}{num_elems}{code}", self.image, start)
                value = values[0] if num_elems == 1 else list(values)
            yield num, value
            offset = nxt

    # -- variable data ---------------------------------------------------
    def _variable_cpr(self, var: Variable) -> list[int]:
        self._record(var.cpr_offset, CPR)
        _, _, ctype, _ra, pcount = struct.unpack_from(">qiiii", self.image, var.cpr_offset)
        if ctype != GZIP_CTYPE:
            raise CDFError(f"variable {var.name}: compression type {ctype} is not GZIP")
        return list(struct.unpack_from(f">{pcount}i", self.image, var.cpr_offset + 24))

    def _leaf_blocks(self, head: int, var: Variable, depth: int = 0):
        """Yield (first, last, offset) for every VVR/CVVR in VXR order."""
        if depth > 8:
            raise CDFError(f"variable {var.name}: VXR nesting too deep")
        offset = head
        seen = set()
        while offset:
            if offset in seen:
                raise CDFError(f"variable {var.name}: VXR chain loops")
            seen.add(offset)
            size, _ = self._record(offset, VXR)
            # VXR header: RecordSize(8) RecordType(4) VXRnext(8) Nentries(4)
            # NusedEntries(4) = 28 bytes, then First[N] Last[N] (int32) Offset[N] (int64).
            _, _, nxt, n_entries, n_used = struct.unpack_from(">qiqii", self.image, offset)
            if not 0 <= n_used <= n_entries or 28 + 16 * n_entries > size:
                raise CDFError(f"variable {var.name}: malformed VXR at {offset}")
            firsts = struct.unpack_from(f">{n_entries}i", self.image, offset + 28)
            lasts = struct.unpack_from(f">{n_entries}i", self.image, offset + 28 + 4 * n_entries)
            offs = struct.unpack_from(f">{n_entries}q", self.image, offset + 28 + 8 * n_entries)
            for first, last, child in zip(firsts[:n_used], lasts[:n_used], offs[:n_used]):
                _, ctype = self._record(child, (VXR, VVR, CVVR))
                if ctype == VXR:
                    for leaf in self._leaf_blocks(child, var, depth + 1):
                        if not (first <= leaf[0] <= leaf[1] <= last):
                            raise CDFError(f"variable {var.name}: nested VXR range mismatch")
                        yield leaf
                else:
                    yield first, last, child
            offset = nxt

    def read_records(self, name: str) -> tuple[bytes, dict]:
        """Return the raw contiguous record bytes (CDF data encoding) of a variable.

        Requires every record 0..MaxRec to be physically present exactly once
        (no sparse records, no gaps, no virtual pad records).
        """
        if name not in self.variables:
            raise CDFError(f"variable {name} not in file")
        var = self.variables[name]
        if var.sparse_records:
            raise CDFError(f"variable {name}: sparse records ({var.sparse_records}) unsupported")
        params = self._variable_cpr(var) if var.compressed else None
        rec_bytes = var.record_bytes
        expected_next = 0
        chunks: list[bytes] = []
        stats = {"blocks": 0, "cvvr_blocks": 0, "vvr_blocks": 0, "gzip_params": params}
        for first, last, offset in self._leaf_blocks(var.vxr_head, var):
            if first != expected_next or last < first:
                raise CDFError(f"variable {name}: record block {first}..{last} breaks contiguity at {expected_next}")
            want = (last - first + 1) * rec_bytes
            size, rtype = self._record(offset, (VVR, CVVR))
            if rtype == CVVR:
                if not var.compressed:
                    raise CDFError(f"variable {name}: CVVR in an uncompressed variable")
                (csize,) = struct.unpack_from(">q", self.image, offset + 16)
                if 24 + csize > size:
                    raise CDFError(f"variable {name}: CVVR at {offset} overruns its record")
                data = _gunzip_exact(self.image[offset + 24 : offset + 24 + csize], want,
                                     f"{name} CVVR@{offset}")
                stats["cvvr_blocks"] += 1
            else:
                if size - 12 < want:
                    raise CDFError(f"variable {name}: VVR at {offset} too short")
                data = self.image[offset + 12 : offset + 12 + want]
                stats["vvr_blocks"] += 1
            chunks.append(data)
            stats["blocks"] += 1
            expected_next = last + 1
        if expected_next != var.max_rec + 1:
            raise CDFError(f"variable {name}: blocks cover {expected_next} records, MaxRec+1 is {var.max_rec + 1}")
        return b"".join(chunks), stats

    def read_values(self, name: str) -> tuple[tuple, dict]:
        var = self.variables[name]
        code, width = DATA_TYPES[var.data_type]
        if code == "s":
            raise CDFError(f"variable {name} is character data")
        raw, stats = self.read_records(name)
        count = len(raw) // width
        return struct.unpack(f"{self.byte_order}{count}{code}", raw), stats
