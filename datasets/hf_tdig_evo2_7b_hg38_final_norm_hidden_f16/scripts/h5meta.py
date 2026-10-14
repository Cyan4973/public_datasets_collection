#!/usr/bin/env python3
"""Minimal pure-stdlib HDF5 metadata reader for the TDiG tier-3 files.

Only what the pinned files use is supported: superblock version 0 with
8-byte offsets and lengths, a root group stored as a v1 symbol table
(B-tree type 0 + SNOD + local heap), and version-1 object headers. For each
root-group dataset it reports the dataspace, the datatype (class, size, byte
order, float layout) and the storage layout (contiguous address/size,
chunked, compact) plus whether a filter pipeline is present.

The reader works on a byte prefix of the file (the "head"); any access past
the prefix raises, so callers learn when metadata sits outside the fetched
range instead of silently reading garbage.
"""
from __future__ import annotations

import struct

HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
UNDEF = 0xFFFFFFFFFFFFFFFF


class H5Error(ValueError):
    pass


class Prefix:
    def __init__(self, data: bytes):
        self.data = data

    def read(self, addr: int, n: int) -> bytes:
        if addr < 0 or addr + n > len(self.data):
            raise H5Error(f"metadata read [{addr}, {addr + n}) outside fetched prefix of {len(self.data)} bytes")
        return self.data[addr:addr + n]

    def u(self, addr: int, n: int) -> int:
        return int.from_bytes(self.read(addr, n), "little")


def parse_datatype(b: bytes) -> dict:
    cv = b[0]
    cls, ver = cv & 0x0F, cv >> 4
    bits = b[1] | (b[2] << 8) | (b[3] << 16)
    size = struct.unpack_from("<I", b, 4)[0]
    dt = {"class": cls, "version": ver, "size": size, "byte_order": "big" if bits & 1 else "little"}
    if cls == 0:  # fixed point
        dt["kind"] = "int" if bits & 0x08 else "uint"
        dt["bit_offset"], dt["precision"] = struct.unpack_from("<HH", b, 8)
    elif cls == 1:  # floating point
        dt["kind"] = "float"
        if bits & 0x40:
            raise H5Error("VAX float byte order not supported")
        dt["sign_location"] = (bits >> 8) & 0xFF
        dt["mantissa_norm"] = (bits >> 4) & 0x03
        (dt["bit_offset"], dt["precision"], dt["exp_location"], dt["exp_size"],
         dt["mant_location"], dt["mant_size"], dt["exp_bias"]) = struct.unpack_from("<HHBBBBI", b, 8)
    else:
        dt["kind"] = f"class{cls}"
    return dt


def parse_dataspace(b: bytes) -> list[int]:
    ver, rank, flags = b[0], b[1], b[2]
    if ver == 1:
        off = 8
    elif ver == 2:
        off = 4
    else:
        raise H5Error(f"dataspace version {ver} not supported")
    return [struct.unpack_from("<Q", b, off + 8 * i)[0] for i in range(rank)]


def parse_layout(b: bytes) -> dict:
    ver = b[0]
    if ver != 3:
        raise H5Error(f"layout message version {ver} not supported")
    cls = b[1]
    if cls == 1:
        addr, size = struct.unpack_from("<QQ", b, 2)
        return {"class": "contiguous", "address": addr, "size": size}
    if cls == 0:
        size = struct.unpack_from("<H", b, 2)[0]
        return {"class": "compact", "size": size}
    if cls == 2:
        return {"class": "chunked"}
    raise H5Error(f"layout class {cls} not supported")


def read_object_header(p: Prefix, addr: int) -> list[tuple[int, bytes]]:
    ver = p.u(addr, 1)
    if ver != 1:
        raise H5Error(f"object header version {ver} at {addr} not supported")
    nmsg = p.u(addr + 2, 2)
    hsize = p.u(addr + 8, 4)
    blocks = [(addr + 16, hsize)]
    msgs: list[tuple[int, bytes]] = []
    while blocks:
        start, length = blocks.pop(0)
        pos, end = start, start + length
        while pos + 8 <= end and len(msgs) < nmsg:
            mtype = p.u(pos, 2)
            msize = p.u(pos + 2, 2)
            data = p.read(pos + 8, msize)
            msgs.append((mtype, data))
            if mtype == 0x0010:  # continuation
                caddr, clen = struct.unpack_from("<QQ", data, 0)
                blocks.append((caddr, clen))
            pos += 8 + msize
    if len(msgs) != nmsg:
        raise H5Error(f"object header at {addr}: found {len(msgs)} of {nmsg} messages")
    return msgs


def describe_dataset(p: Prefix, addr: int) -> dict:
    info: dict = {"header_address": addr, "filters": False}
    for mtype, data in read_object_header(p, addr):
        if mtype == 0x0001:
            info["shape"] = parse_dataspace(data)
        elif mtype == 0x0003:
            info["dtype"] = parse_datatype(data)
        elif mtype == 0x0008:
            info["layout"] = parse_layout(data)
        elif mtype == 0x000B:
            info["filters"] = True
        elif mtype == 0x0011:
            info["is_group"] = True
    return info


def root_entries(p: Prefix) -> dict[str, int]:
    if p.read(0, 8) != HDF5_SIGNATURE:
        raise H5Error("missing HDF5 signature")
    if p.u(8, 1) != 0:
        raise H5Error(f"superblock version {p.u(8, 1)} not supported")
    if p.u(13, 1) != 8 or p.u(14, 1) != 8:
        raise H5Error("only 8-byte offsets/lengths supported")
    base = p.u(24, 8)
    if base != 0:
        raise H5Error("nonzero base address not supported")
    root = 56  # root group symbol table entry
    cache_type = p.u(root + 16, 4)
    if cache_type != 1:
        raise H5Error("root group entry does not cache a symbol table")
    btree, heap = p.u(root + 24, 8), p.u(root + 32, 8)
    if p.read(heap, 4) != b"HEAP":
        raise H5Error("missing local heap signature")
    heap_data = p.u(heap + 24, 8)
    heap_size = p.u(heap + 8, 8)
    names_blob = p.read(heap_data, heap_size)

    def name_at(off: int) -> str:
        end = names_blob.index(b"\x00", off)
        return names_blob[off:end].decode("ascii")

    entries: dict[str, int] = {}

    def walk(node: int) -> None:
        if p.read(node, 4) != b"TREE":
            raise H5Error(f"missing B-tree signature at {node}")
        if p.u(node + 4, 1) != 0:
            raise H5Error("not a group B-tree")
        level = p.u(node + 5, 1)
        used = p.u(node + 6, 2)
        pos = node + 24
        for i in range(used):
            child = p.u(pos + 8, 8)
            pos += 16
            if level > 0:
                walk(child)
            else:
                if p.read(child, 4) != b"SNOD":
                    raise H5Error(f"missing SNOD signature at {child}")
                nsym = p.u(child + 6, 2)
                for j in range(nsym):
                    e = child + 8 + 40 * j
                    entries[name_at(p.u(e, 8))] = p.u(e + 8, 8)

    walk(btree)
    return entries


def describe_file(head: bytes) -> dict:
    p = Prefix(head)
    out = {"eof": p.u(40, 8), "datasets": {}}
    for name, addr in sorted(root_entries(p).items()):
        out["datasets"][name] = describe_dataset(p, addr)
    return out


if __name__ == "__main__":
    import json
    import sys

    with open(sys.argv[1], "rb") as fh:
        print(json.dumps(describe_file(fh.read()), indent=1))
