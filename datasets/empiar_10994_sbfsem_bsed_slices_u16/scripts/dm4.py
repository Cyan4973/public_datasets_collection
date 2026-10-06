#!/usr/bin/env python3
"""Minimal pure-stdlib Gatan DigitalMicrograph 4 (DM4) tag-tree reader.

Layout (all structural integers big-endian, tag *values* in the byte order
declared by the header):

  header   u32 version (=4), u64 root_length (= file_size - 24),
           u32 byte_order (1 = little-endian values)
  group    u8 sorted, u8 open, u64 tag_count, then tag_count tags
  tag      u8 kind (0x14 group, 0x15 data), u16 name_length, name bytes,
           u64 tag_length (bytes that follow this field), then
           group body | data body
  data     b'%%%%', u64 info_count, info_count x u64 type descriptors,
           value bytes
  trailer  8 zero bytes after the root group

Type descriptors: [t] for simple types; [15, name_len, n, (fname_len, ftype)*n]
for structs; [20, elem_type, count] for arrays of simple types;
[20, 15, name_len, n, (fname_len, ftype)*n, count] for arrays of structs;
[18, length] for strings (skipped by tag_length).

No alignment is assumed anywhere: the image Data array may start at an odd
byte offset. Large arrays are never decoded here, only located.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

SIMPLE = {
    2: ("h", 2),   # int16
    3: ("i", 4),   # int32
    4: ("H", 2),   # uint16
    5: ("I", 4),   # uint32
    6: ("f", 4),   # float32
    7: ("d", 8),   # float64
    8: ("?", 1),   # bool
    9: ("b", 1),   # int8 / char
    10: ("B", 1),  # uint8 / octet
    11: ("q", 8),  # int64
    12: ("Q", 8),  # uint64
}
TAG_GROUP = 0x14
TAG_DATA = 0x15
DECODE_LIMIT = 4096  # arrays above this many bytes are located, not decoded
MAX_DEPTH = 64


class DM4Error(ValueError):
    pass


@dataclass
class Data:
    info: list
    offset: int        # absolute offset of the first value byte
    length: int        # value byte count
    elem_type: int | None = None   # for arrays of simple types
    count: int | None = None       # for arrays of simple types
    value: object = None           # decoded scalar / struct tuple / small array


@dataclass
class Group:
    offset: int
    entries: list = field(default_factory=list)  # [(name, Group|Data)]

    def get(self, name):
        hits = [node for (n, node) in self.entries if n == name]
        if len(hits) != 1:
            raise DM4Error(f"expected exactly one tag named {name!r}, found {len(hits)}")
        return hits[0]

    def has(self, name):
        return any(n == name for (n, _) in self.entries)


class BytesReader:
    def __init__(self, buf):
        self.buf = memoryview(buf)
        self.size = len(buf)

    def read(self, off, n):
        if off < 0 or n < 0 or off + n > self.size:
            raise DM4Error(f"read past end: off={off} n={n} size={self.size}")
        return self.buf[off:off + n].tobytes()


def _struct_fields(info, pos):
    """Parse '15, name_len, n, (fname_len, ftype)*n' starting at info[pos]."""
    if pos + 3 > len(info) or info[pos] != 15:
        raise DM4Error(f"bad struct descriptor {info}")
    n = info[pos + 2]
    end = pos + 3 + 2 * n
    if end > len(info):
        raise DM4Error(f"truncated struct descriptor {info}")
    ftypes = [info[pos + 4 + 2 * i] for i in range(n)]
    for t in ftypes:
        if t not in SIMPLE:
            raise DM4Error(f"non-simple struct field type {t} in {info}")
    return ftypes, end


def _value_layout(info):
    """Return (byte_length or None, elem_type, count, fmt) for a descriptor."""
    t = info[0]
    if t in SIMPLE:
        if len(info) != 1:
            raise DM4Error(f"bad simple descriptor {info}")
        return SIMPLE[t][1], None, None, SIMPLE[t][0]
    if t == 15:
        ftypes, end = _struct_fields(info, 0)
        if end != len(info):
            raise DM4Error(f"trailing struct descriptor words {info}")
        return sum(SIMPLE[f][1] for f in ftypes), None, None, "".join(SIMPLE[f][0] for f in ftypes)
    if t == 20:
        if len(info) < 3:
            raise DM4Error(f"bad array descriptor {info}")
        et = info[1]
        if et in SIMPLE:
            if len(info) != 3:
                raise DM4Error(f"bad simple-array descriptor {info}")
            return SIMPLE[et][1] * info[2], et, info[2], None
        if et == 15:
            ftypes, end = _struct_fields(info, 1)
            if end + 1 != len(info):
                raise DM4Error(f"bad struct-array descriptor {info}")
            return sum(SIMPLE[f][1] for f in ftypes) * info[end], None, info[end], None
        return None, None, None, None  # arrays of strings/arrays: skip by length
    return None, None, None, None      # strings (18) and anything else: skip by length


def _parse_data(r, p, tag_len, endian):
    if r.read(p, 4) != b"%%%%":
        raise DM4Error(f"missing %%%% delimiter at {p}")
    (ninfo,) = struct.unpack(">Q", r.read(p + 4, 8))
    if ninfo == 0 or ninfo > 1024:
        raise DM4Error(f"implausible info count {ninfo} at {p}")
    info = list(struct.unpack(f">{ninfo}Q", r.read(p + 12, 8 * ninfo)))
    voff = p + 12 + 8 * ninfo
    vlen = tag_len - 12 - 8 * ninfo
    if vlen < 0:
        raise DM4Error(f"negative value length at {p}")
    expect, et, count, fmt = _value_layout(info)
    if expect is not None and expect != vlen:
        raise DM4Error(f"descriptor {info} implies {expect} value bytes but tag holds {vlen} (at {p})")
    node = Data(info=info, offset=voff, length=vlen, elem_type=et, count=count)
    if fmt is not None:
        vals = struct.unpack(endian + fmt, r.read(voff, vlen))
        node.value = vals[0] if len(vals) == 1 else vals
    elif et is not None and vlen <= DECODE_LIMIT:
        node.value = struct.unpack(f"{endian}{count}{SIMPLE[et][0]}", r.read(voff, vlen))
    return node


def _parse_group(r, p, end, endian, depth):
    if depth > MAX_DEPTH:
        raise DM4Error("tag tree too deep")
    sorted_flag, open_flag = r.read(p, 2)
    if sorted_flag > 1 or open_flag > 1:
        raise DM4Error(f"bad group flags at {p}")
    (ntags,) = struct.unpack(">Q", r.read(p + 2, 8))
    g = Group(offset=p)
    q = p + 10
    for _ in range(ntags):
        kind = r.read(q, 1)[0]
        (nlen,) = struct.unpack(">H", r.read(q + 1, 2))
        name = r.read(q + 3, nlen).decode("latin-1")
        (tlen,) = struct.unpack(">Q", r.read(q + 3 + nlen, 8))
        body = q + 11 + nlen
        if body + tlen > end:
            raise DM4Error(f"tag {name!r} at {q} overruns its parent ({body + tlen} > {end})")
        if kind == TAG_GROUP:
            child = _parse_group(r, body, body + tlen, endian, depth + 1)
        elif kind == TAG_DATA:
            child = _parse_data(r, body, tlen, endian)
        else:
            raise DM4Error(f"bad tag kind {kind:#x} at {q}")
        g.entries.append((name, child))
        q = body + tlen
    if q != end:
        raise DM4Error(f"group at {p} ends at {q}, expected {end}")
    return g


def parse(r):
    """Parse a whole DM4 tag tree from a reader with .read(off, n) and .size."""
    version, root_len, order = struct.unpack(">IQI", r.read(0, 16))
    if version != 4:
        raise DM4Error(f"not a DM4 file (version {version})")
    if order not in (0, 1):
        raise DM4Error(f"bad byte-order flag {order}")
    if root_len + 24 != r.size:
        raise DM4Error(f"root length {root_len} + 24 != file size {r.size}")
    endian = "<" if order == 1 else ">"
    root = _parse_group(r, 16, r.size - 8, endian, 0)
    if r.read(r.size - 8, 8) != b"\0" * 8:
        raise DM4Error("missing 8-byte zero trailer")
    return order, root


@dataclass
class Image:
    data_offset: int
    width: int
    height: int
    data_type: int
    pixel_depth: int
    elem_type: int
    count: int


def image_entry(root, index):
    lst = root.get("ImageList")
    if not isinstance(lst, Group):
        raise DM4Error("ImageList is not a group")
    if index >= len(lst.entries):
        raise DM4Error(f"ImageList has {len(lst.entries)} entries, wanted index {index}")
    name, entry = lst.entries[index]
    if name != "" or not isinstance(entry, Group):
        raise DM4Error(f"ImageList[{index}] is not an unnamed group")
    return entry


def image_of(entry):
    idata = entry.get("ImageData")
    data = idata.get("Data")
    dims = idata.get("Dimensions")
    if not isinstance(data, Data) or not isinstance(dims, Group):
        raise DM4Error("malformed ImageData")
    dvals = []
    for (n, d) in dims.entries:
        if n != "" or not isinstance(d, Data) or d.info[0] not in (3, 5):
            raise DM4Error("malformed Dimensions")
        dvals.append(d.value)
    dt = idata.get("DataType")
    pd = idata.get("PixelDepth")
    if not isinstance(dt, Data) or dt.info[0] not in (3, 5) or not isinstance(pd, Data) or pd.info[0] not in (3, 5):
        raise DM4Error("malformed DataType/PixelDepth")
    if data.elem_type is None:
        raise DM4Error(f"Data is not an array of a simple type: {data.info}")
    if len(dvals) != 2:
        raise DM4Error(f"expected a 2-D image, got dimensions {dvals}")
    return Image(data_offset=data.offset, width=dvals[0], height=dvals[1], data_type=dt.value,
                 pixel_depth=pd.value, elem_type=data.elem_type, count=data.count)


def lookup(group, path):
    """Follow a '/'-separated path of tag names; '#k' selects the k-th entry."""
    node = group
    for part in path.split("/"):
        if not isinstance(node, Group):
            raise DM4Error(f"{path}: {part!r} reached through a data tag")
        if part.startswith("#"):
            node = node.entries[int(part[1:])][1]
        else:
            node = node.get(part)
    return node


def u16_text(node):
    """Decode a DM text tag stored as an array of uint16 code units."""
    if not isinstance(node, Data) or node.elem_type != 4 or node.value is None:
        raise DM4Error("not a short uint16 text array")
    return "".join(chr(c) for c in node.value)


def undecoded_ranges(group):
    """(offset, length) of every non-empty value the parser located but did not read."""
    out = []
    for (_, node) in group.entries:
        if isinstance(node, Group):
            out.extend(undecoded_ranges(node))
        elif node.value is None and node.length > 0:
            out.append((node.offset, node.length))
    return sorted(out)


def skeleton_sha256(r, root):
    """SHA-256 over every byte the tag walk reads: the file minus undecoded values.

    The excluded ranges are the large image arrays (thumbnail and main Data)
    and a few undecoded display tables, so this digest pins all structure and
    metadata yet can be computed from small HTTP range probes.
    """
    import hashlib

    h = hashlib.sha256()
    pos = 0
    for off, length in undecoded_ranges(root):
        if off < pos:
            raise DM4Error("overlapping value ranges")
        h.update(r.read(pos, off - pos))
        pos = off + length
    h.update(r.read(pos, r.size - pos))
    return h.hexdigest()
