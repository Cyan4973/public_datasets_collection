#!/usr/bin/env python3
"""Pure-stdlib reader for the PDEBench 2D CFD HDF5 metadata.

The pinned file is 88 GB, so the recipe never holds it locally. It fetches
only a few small metadata byte ranges, which this module reads through an
absolute-offset `Sparse` view. Only the structures the pinned file actually
uses are supported: superblock version 0 with 8-byte offsets and lengths, a
root group stored as a single-level version-1 group B-tree with
symbol-table nodes and a version-0 local heap, version-1 object headers
(including continuation blocks), version-1/2 dataspace messages, IEEE
float datatype messages and version-3 layout messages. Anything else fails
loudly instead of being guessed.

Usage:
  pdebench_h5.py describe START:FILE [START:FILE ...]
"""

from __future__ import annotations

import argparse
import json
import math
import struct

HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"

MSG_DATASPACE = 0x0001
MSG_DATATYPE = 0x0003
MSG_EXTERNAL_FILES = 0x0007
MSG_LAYOUT = 0x0008
MSG_FILTER_PIPELINE = 0x000B
MSG_CONTINUATION = 0x0010

# H5T_IEEE_F32LE: class 1 version 1, little-endian, 32-bit, 8-bit exponent at
# bit 23, 23-bit mantissa at bit 0, bias 127.
H5T_IEEE_F32LE = bytes.fromhex("11201f000400000000002000170800177f000000")


class H5Error(ValueError):
    pass


class Sparse:
    """Absolute-offset view over a few fetched byte ranges of one remote file."""

    def __init__(self, segments: list[tuple[int, bytes]]):
        self.segments = sorted((int(start), bytes(data)) for start, data in segments)

    def read(self, offset: int, size: int) -> bytes:
        for start, data in self.segments:
            if start <= offset and offset + size <= start + len(data):
                return data[offset - start : offset - start + size]
        raise H5Error(f"bytes {offset}+{size} are outside the fetched metadata ranges")

    def cstring(self, offset: int) -> str:
        for start, data in self.segments:
            if start <= offset < start + len(data):
                end = data.find(b"\0", offset - start)
                if end < 0:
                    raise H5Error(f"unterminated link name at {offset}")
                return data[offset - start : end].decode("ascii")
        raise H5Error(f"link name at {offset} is outside the fetched metadata ranges")


def u8(buf: Sparse, offset: int) -> int:
    return buf.read(offset, 1)[0]


def u16(buf: Sparse, offset: int) -> int:
    return struct.unpack("<H", buf.read(offset, 2))[0]


def u32(buf: Sparse, offset: int) -> int:
    return struct.unpack("<I", buf.read(offset, 4))[0]


def u64(buf: Sparse, offset: int) -> int:
    return struct.unpack("<Q", buf.read(offset, 8))[0]


def p8(payload: bytes, offset: int) -> int:
    if offset + 1 > len(payload):
        raise H5Error("truncated message payload")
    return payload[offset]


def p16(payload: bytes, offset: int) -> int:
    if offset + 2 > len(payload):
        raise H5Error("truncated message payload")
    return struct.unpack_from("<H", payload, offset)[0]


def p64(payload: bytes, offset: int) -> int:
    if offset + 8 > len(payload):
        raise H5Error("truncated message payload")
    return struct.unpack_from("<Q", payload, offset)[0]


def parse_superblock(buf: Sparse) -> dict:
    if buf.read(0, 8) != HDF5_SIGNATURE:
        raise H5Error("missing HDF5 signature at offset 0")
    version = u8(buf, 8)
    if version != 0:
        raise H5Error(f"unsupported superblock version {version}")
    if (u8(buf, 13), u8(buf, 14)) != (8, 8):
        raise H5Error(f"unexpected offset/length sizes {u8(buf, 13)}/{u8(buf, 14)}")
    if u64(buf, 24) != 0:
        raise H5Error(f"unexpected base address {u64(buf, 24)}")
    return {
        "superblock_version": version,
        "eof_address": u64(buf, 40),
        "root_object_header": u64(buf, 64),
        "root_cache_type": u32(buf, 72),
        "root_btree": u64(buf, 80),
        "root_heap": u64(buf, 88),
    }


def root_heap(buf: Sparse, sb: dict) -> dict:
    address = sb["root_heap"]
    if buf.read(address, 4) != b"HEAP" or u8(buf, address + 4) != 0:
        raise H5Error(f"no version-0 local heap at {address}")
    return {"address": address, "data_size": u64(buf, address + 8), "data_address": u64(buf, address + 24)}


def root_links(buf: Sparse, sb: dict) -> dict[str, int]:
    if sb["root_cache_type"] != 1:
        raise H5Error(f"root symbol-table entry has cache type {sb['root_cache_type']}, expected 1")
    heap = root_heap(buf, sb)
    btree = sb["root_btree"]
    if buf.read(btree, 4) != b"TREE" or u8(buf, btree + 4) != 0:
        raise H5Error(f"no version-1 group B-tree at {btree}")
    if u8(buf, btree + 5) != 0:
        raise H5Error(f"multi-level root group B-tree (level {u8(buf, btree + 5)}) is not supported")
    links: dict[str, int] = {}
    cursor = btree + 24  # signature, type, level, entry count, left and right siblings
    for _ in range(u16(buf, btree + 6)):
        child = u64(buf, cursor + 8)  # skip the 8-byte heap-offset key
        cursor += 16
        if buf.read(child, 4) != b"SNOD" or u8(buf, child + 4) != 1:
            raise H5Error(f"no version-1 symbol-table node at {child}")
        for index in range(u16(buf, child + 6)):
            entry = child + 8 + index * 40
            name_offset = u64(buf, entry)
            if name_offset >= heap["data_size"]:
                raise H5Error(f"link name offset {name_offset} beyond heap data size")
            name = buf.cstring(heap["data_address"] + name_offset)
            if name in links:
                raise H5Error(f"duplicate root link {name!r}")
            links[name] = u64(buf, entry + 8)
    return links


def object_messages(buf: Sparse, address: int) -> list[tuple[int, bytes]]:
    if u8(buf, address) != 1:
        raise H5Error(f"unsupported object-header version at {address}: {u8(buf, address)}")
    total = u16(buf, address + 2)
    blocks = [(address + 16, u32(buf, address + 8))]
    messages: list[tuple[int, bytes]] = []
    seen_blocks: set[int] = set()
    while blocks:
        start, size = blocks.pop(0)
        if start in seen_blocks:
            raise H5Error(f"cyclic object-header continuation at {start}")
        seen_blocks.add(start)
        block = buf.read(start, size)
        cursor = 0
        while cursor + 8 <= size and len(messages) < total:
            mtype, msize = struct.unpack_from("<HH", block, cursor)
            if cursor + 8 + msize > size:
                raise H5Error(f"object-header message at {start + cursor} overruns its block")
            payload = block[cursor + 8 : cursor + 8 + msize]
            messages.append((mtype, payload))
            if mtype == MSG_CONTINUATION:
                blocks.append((p64(payload, 0), p64(payload, 8)))
            cursor += 8 + msize
    if len(messages) != total:
        raise H5Error(f"object header at {address}: found {len(messages)} of {total} messages")
    return messages


def only(messages: list[tuple[int, bytes]], mtype: int) -> bytes:
    found = [payload for kind, payload in messages if kind == mtype]
    if len(found) != 1:
        raise H5Error(f"expected exactly one message of type {mtype:#06x}, found {len(found)}")
    return found[0]


def parse_dataspace(payload: bytes) -> tuple[int, ...]:
    version = p8(payload, 0)
    rank = p8(payload, 1)
    if version == 1:
        dims_at = 8
    elif version == 2:
        if p8(payload, 3) != 1:
            raise H5Error(f"dataspace v2 type {payload[3]} is not simple")
        dims_at = 4
    else:
        raise H5Error(f"unsupported dataspace version {version}")
    return tuple(p64(payload, dims_at + 8 * i) for i in range(rank))


def parse_layout(payload: bytes) -> dict:
    version = p8(payload, 0)
    if version != 3:
        raise H5Error(f"unsupported layout message version {version}")
    layout_class = p8(payload, 1)
    if layout_class == 1:
        return {"class": "contiguous", "address": p64(payload, 2), "size": p64(payload, 10)}
    if layout_class == 0:
        return {"class": "compact", "size": p16(payload, 2)}
    if layout_class == 2:
        return {"class": "chunked"}
    raise H5Error(f"unknown layout class {layout_class}")


def describe_dataset(buf: Sparse, address: int) -> dict:
    messages = object_messages(buf, address)
    datatype = only(messages, MSG_DATATYPE)
    return {
        "object_header": address,
        "shape": list(parse_dataspace(only(messages, MSG_DATASPACE))),
        "datatype_hex": datatype.hex(),
        "is_f32le": datatype[: len(H5T_IEEE_F32LE)] == H5T_IEEE_F32LE
        and not any(datatype[len(H5T_IEEE_F32LE) :]),
        "layout": parse_layout(only(messages, MSG_LAYOUT)),
        "has_filter_pipeline": any(kind == MSG_FILTER_PIPELINE for kind, _p in messages),
        "has_external_files": any(kind == MSG_EXTERNAL_FILES for kind, _p in messages),
        "message_types": sorted({kind for kind, _p in messages}),
    }


def describe(buf: Sparse) -> dict:
    sb = parse_superblock(buf)
    links = root_links(buf, sb)
    return {
        "superblock": sb,
        "root_heap": root_heap(buf, sb),
        "datasets": {name: describe_dataset(buf, addr) for name, addr in sorted(links.items())},
    }


def validate_density(
    report: dict,
    *,
    file_size: int,
    shape: tuple[int, ...],
    address: int,
    expected_root: set[str],
) -> dict:
    """Assert the exact layout the recipe depends on; return the density entry."""
    if report["superblock"]["eof_address"] != file_size:
        raise H5Error(
            f"HDF5 end-of-file address {report['superblock']['eof_address']} != remote size {file_size}"
        )
    names = set(report["datasets"])
    if names != expected_root:
        raise H5Error(f"root datasets changed: {sorted(names)}")
    density = report["datasets"]["density"]
    if tuple(density["shape"]) != tuple(shape):
        raise H5Error(f"/density shape changed: {density['shape']}")
    if not density["is_f32le"]:
        raise H5Error(f"/density is not H5T_IEEE_F32LE: {density['datatype_hex']}")
    if density["has_filter_pipeline"] or density["has_external_files"]:
        raise H5Error("/density has a filter pipeline or external storage")
    expected = {"class": "contiguous", "address": address, "size": 4 * math.prod(shape)}
    if density["layout"] != expected:
        raise H5Error(f"/density layout changed: {density['layout']}")
    if address + expected["size"] > file_size:
        raise H5Error("/density extends beyond the end of the file")
    # No other dataset may overlap the density byte range.
    for name, info in report["datasets"].items():
        layout = info["layout"]
        if name == "density" or layout.get("class") != "contiguous":
            continue
        lo, hi = layout["address"], layout["address"] + layout["size"]
        if lo < address + expected["size"] and address < hi:
            raise H5Error(f"dataset {name!r} overlaps /density")
    return density


def load_segments(specs: list[str]) -> Sparse:
    segments = []
    for spec in specs:
        start, _, path = spec.partition(":")
        with open(path, "rb") as handle:
            segments.append((int(start), handle.read()))
    return Sparse(segments)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("describe")
    d.add_argument("segments", nargs="+", help="START:PATH for each fetched byte range")
    args = parser.parse_args()
    print(json.dumps(describe(load_segments(args.segments)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (H5Error, OSError, struct.error) as exc:
        raise SystemExit(f"pdebench_h5: {exc}") from exc
