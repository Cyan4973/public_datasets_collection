#!/usr/bin/env python3
"""Minimal pure-stdlib NetCDF classic-family header parser (CDF-1, CDF-2, CDF-5).

Only the header grammar is implemented (magic, numrecs, dimension list,
global attributes, variable list with per-variable attributes, nc_type,
vsize and begin). Variable payload bytes are left to the caller, which reads
`vsize` big-endian bytes at `begin` for non-record variables.

Grammar reference: the NetCDF "File Format Specification" and the PnetCDF
CDF-5 extension. In CDF-5 every NON_NEG count/length/dimid/vsize is a 64-bit
big-endian integer and every OFFSET is 64-bit; in CDF-2 counts are 32-bit and
offsets 64-bit; in CDF-1 both are 32-bit.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

NC_DIMENSION = 0x0A
NC_VARIABLE = 0x0B
NC_ATTRIBUTE = 0x0C

# nc_type code -> (name, element size, struct code)
NC_TYPES = {
    1: ("NC_BYTE", 1, "b"),
    2: ("NC_CHAR", 1, "c"),
    3: ("NC_SHORT", 2, "h"),
    4: ("NC_INT", 4, "i"),
    5: ("NC_FLOAT", 4, "f"),
    6: ("NC_DOUBLE", 8, "d"),
    7: ("NC_UBYTE", 1, "B"),
    8: ("NC_USHORT", 2, "H"),
    9: ("NC_UINT", 4, "I"),
    10: ("NC_INT64", 8, "q"),
    11: ("NC_UINT64", 8, "Q"),
}
NC_DOUBLE = 6


class CDFError(ValueError):
    pass


class NeedMoreBytes(CDFError):
    """The supplied prefix ends before the header does."""


@dataclass
class Dim:
    name: str
    length: int  # 0 means the record (unlimited) dimension


@dataclass
class Var:
    name: str
    dimids: list[int]
    attrs: dict
    nc_type: int
    vsize: int
    begin: int
    shape: list[int] = field(default_factory=list)
    is_record: bool = False

    @property
    def type_name(self) -> str:
        return NC_TYPES[self.nc_type][0]

    @property
    def element_size(self) -> int:
        return NC_TYPES[self.nc_type][1]

    @property
    def value_count(self) -> int:
        count = 1
        for length in self.shape:
            count *= length
        return count


@dataclass
class Header:
    version: int
    numrecs: int
    dims: list[Dim]
    gattrs: dict
    vars: list[Var]
    header_end: int  # byte offset just past the parsed header

    def var(self, name: str) -> Var:
        for item in self.vars:
            if item.name == name:
                return item
        raise CDFError(f"variable {name!r} not present")

    def dim(self, name: str) -> Dim:
        for item in self.dims:
            if item.name == name:
                return item
        raise CDFError(f"dimension {name!r} not present")


class _Reader:
    def __init__(self, data: bytes, version: int):
        self.data = data
        self.pos = 0
        self.version = version

    def take(self, count: int) -> bytes:
        if count < 0:
            raise CDFError(f"negative length {count}")
        end = self.pos + count
        if end > len(self.data):
            raise NeedMoreBytes(f"header truncated at byte {len(self.data)} (need {end})")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def int32(self) -> int:
        return struct.unpack(">i", self.take(4))[0]

    def int64(self) -> int:
        return struct.unpack(">q", self.take(8))[0]

    def non_neg(self) -> int:
        value = self.int64() if self.version == 5 else self.int32()
        if value < 0:
            raise CDFError(f"negative NON_NEG value {value} at byte {self.pos}")
        return value

    def offset(self) -> int:
        value = self.int32() if self.version == 1 else self.int64()
        if value < 0:
            raise CDFError(f"negative OFFSET value {value} at byte {self.pos}")
        return value

    def pad4(self, count: int) -> None:
        padding = (-count) % 4
        if padding:
            self.take(padding)

    def name(self) -> str:
        length = self.non_neg()
        if length > 1 << 20:
            raise CDFError(f"implausible name length {length}")
        raw = self.take(length)
        self.pad4(length)
        return raw.decode("utf-8")

    def list_header(self, expected_tag: int) -> int:
        tag = self.int32()
        count = self.non_neg()
        if tag == 0:
            if count != 0:
                raise CDFError(f"ABSENT list with nonzero count {count}")
            return 0
        if tag != expected_tag:
            raise CDFError(f"expected list tag {expected_tag:#x}, got {tag:#x} at byte {self.pos}")
        return count

    def attrs(self) -> dict:
        result: dict = {}
        for _ in range(self.list_header(NC_ATTRIBUTE)):
            attr_name = self.name()
            nc_type = self.int32()
            if nc_type not in NC_TYPES:
                raise CDFError(f"attribute {attr_name!r}: unknown nc_type {nc_type}")
            count = self.non_neg()
            _, size, code = NC_TYPES[nc_type]
            raw = self.take(count * size)
            self.pad4(count * size)
            if nc_type == 2:
                result[attr_name] = raw.decode("utf-8", errors="replace").rstrip("\x00")
            else:
                values = struct.unpack(f">{count}{code}", raw)
                result[attr_name] = values[0] if count == 1 else list(values)
        return result


def parse_header(data: bytes) -> Header:
    """Parse a NetCDF classic-family header from a byte prefix of the file."""
    if len(data) < 4:
        raise NeedMoreBytes("fewer than 4 bytes")
    if data[:3] != b"CDF" or data[3] not in (1, 2, 5):
        raise CDFError(f"bad magic {data[:4]!r}")
    reader = _Reader(data, data[3])
    reader.pos = 4
    if reader.version == 5:
        raw = reader.take(8)
        numrecs = -1 if raw == b"\xff" * 8 else struct.unpack(">q", raw)[0]
    else:
        raw = reader.take(4)
        numrecs = -1 if raw == b"\xff" * 4 else struct.unpack(">i", raw)[0]
    dims = []
    for _ in range(reader.list_header(NC_DIMENSION)):
        dim_name = reader.name()
        dims.append(Dim(dim_name, reader.non_neg()))
    gattrs = reader.attrs()
    variables = []
    for _ in range(reader.list_header(NC_VARIABLE)):
        var_name = reader.name()
        rank = reader.non_neg()
        if rank > 64:
            raise CDFError(f"variable {var_name!r}: implausible rank {rank}")
        dimids = [reader.non_neg() for _ in range(rank)]
        for dimid in dimids:
            if dimid >= len(dims):
                raise CDFError(f"variable {var_name!r}: dimid {dimid} out of range")
        vattrs = reader.attrs()
        nc_type = reader.int32()
        if nc_type not in NC_TYPES:
            raise CDFError(f"variable {var_name!r}: unknown nc_type {nc_type}")
        vsize = reader.non_neg()
        begin = reader.offset()
        shape = [dims[d].length for d in dimids]
        is_record = bool(dimids) and dims[dimids[0]].length == 0
        variables.append(Var(var_name, dimids, vattrs, nc_type, vsize, begin, shape, is_record))
    return Header(reader.version, numrecs, dims, gattrs, variables, reader.pos)


# ---------------------------------------------------------------------------
# Synthetic writer used only by the self-test.


def _w_non_neg(version: int, value: int) -> bytes:
    return struct.pack(">q" if version == 5 else ">i", value)


def _w_name(version: int, text: str) -> bytes:
    raw = text.encode("utf-8")
    return _w_non_neg(version, len(raw)) + raw + b"\x00" * ((-len(raw)) % 4)


def _w_attrs(version: int, attrs: list[tuple[str, int, object]]) -> bytes:
    if not attrs:
        return b"\x00\x00\x00\x00" + _w_non_neg(version, 0)
    out = struct.pack(">i", NC_ATTRIBUTE) + _w_non_neg(version, len(attrs))
    for attr_name, nc_type, value in attrs:
        out += _w_name(version, attr_name) + struct.pack(">i", nc_type)
        if nc_type == 2:
            raw = str(value).encode("utf-8")
            count = len(raw)
        else:
            values = value if isinstance(value, list) else [value]
            count = len(values)
            raw = struct.pack(f">{count}{NC_TYPES[nc_type][2]}", *values)
        out += _w_non_neg(version, count) + raw + b"\x00" * ((-len(raw)) % 4)
    return out


def write_synthetic(version: int, dims: list[tuple[str, int]], gattrs, variables) -> bytes:
    """Build a complete classic-family file. `variables` items are
    (name, [dim names], attrs, nc_type, payload_bytes_big_endian)."""
    dim_index = {name: i for i, (name, _) in enumerate(dims)}

    def header(begins: list[int]) -> bytes:
        out = b"CDF" + bytes([version]) + _w_non_neg(version, 0)
        out += struct.pack(">i", NC_DIMENSION) + _w_non_neg(version, len(dims))
        for name, length in dims:
            out += _w_name(version, name) + _w_non_neg(version, length)
        out += _w_attrs(version, gattrs)
        out += struct.pack(">i", NC_VARIABLE) + _w_non_neg(version, len(variables))
        for (name, var_dims, attrs, nc_type, payload), begin in zip(variables, begins):
            out += _w_name(version, name) + _w_non_neg(version, len(var_dims))
            for dim_name in var_dims:
                out += _w_non_neg(version, dim_index[dim_name])
            out += _w_attrs(version, attrs) + struct.pack(">i", nc_type)
            vsize = len(payload) + ((-len(payload)) % 4)
            out += _w_non_neg(version, vsize)
            out += struct.pack(">i" if version == 1 else ">q", begin)
        return out

    probe = header([0] * len(variables))
    begins = []
    cursor = len(probe)
    for _, _, _, _, payload in variables:
        begins.append(cursor)
        cursor += len(payload) + ((-len(payload)) % 4)
    body = header(begins)
    assert len(body) == len(probe)
    for _, _, _, _, payload in variables:
        body += payload + b"\x00" * ((-len(payload)) % 4)
    return body
