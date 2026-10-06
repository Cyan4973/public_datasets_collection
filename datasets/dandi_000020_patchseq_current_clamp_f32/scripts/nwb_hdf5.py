#!/usr/bin/env python3
"""Minimal pure-stdlib HDF5 reader for the DANDI:000020 Allen Patch-seq NWB files.

Scope (exactly what the pinned files use, everything else is a hard error):
- superblock version 0 with 8-byte offsets and lengths
- version-1 object headers with continuation messages
- old-style groups (symbol-table message, v1 group B-tree, local heap, SNOD);
  compact link messages are also accepted, dense (fractal-heap) groups are not
- attribute messages v1/v2/v3 with fixed-point, float, fixed-length string and
  variable-length string datatypes (vlen strings resolved via global heap GCOL)
- dataset layout message v3 (compact, contiguous, chunked with a v1 chunk B-tree)
- filter pipeline v1/v2 with shuffle (2) and deflate (1) only

Addresses equal to the undefined address 0xffffffffffffffff are never
dereferenced.
"""
from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89HDF\r\n\x1a\n"
UNDEF = 0xFFFFFFFFFFFFFFFF

MSG_NIL = 0x00
MSG_DATASPACE = 0x01
MSG_LINK_INFO = 0x02
MSG_DATATYPE = 0x03
MSG_LINK = 0x06
MSG_LAYOUT = 0x08
MSG_FILTERS = 0x0B
MSG_ATTRIBUTE = 0x0C
MSG_CONTINUATION = 0x10
MSG_SYMBOL_TABLE = 0x11
MSG_ATTRIBUTE_INFO = 0x15

FILTER_DEFLATE = 1
FILTER_SHUFFLE = 2


class H5Error(ValueError):
    pass


def _u16(raw, off: int) -> int:
    return struct.unpack("<H", raw[off : off + 2])[0]


def _u32(raw, off: int) -> int:
    return struct.unpack("<I", raw[off : off + 4])[0]


def _u64(raw, off: int) -> int:
    return struct.unpack("<Q", raw[off : off + 8])[0]


def _pad8(n: int) -> int:
    return (n + 7) & ~7


def unshuffle(data: bytes, element_size: int) -> bytes:
    """Inverse of the HDF5 byte-shuffle filter."""
    if element_size <= 1:
        return bytes(data)
    count = len(data) // element_size
    out = bytearray(len(data))
    for byte_index in range(element_size):
        out[byte_index : count * element_size : element_size] = data[
            byte_index * count : (byte_index + 1) * count
        ]
    tail = count * element_size
    out[tail:] = data[tail:]
    return bytes(out)


def shuffle(data: bytes, element_size: int) -> bytes:
    """Forward HDF5 byte-shuffle (used only by the synthetic self-test)."""
    count = len(data) // element_size
    parts = [data[j : count * element_size : element_size] for j in range(element_size)]
    return b"".join(parts) + data[count * element_size :]


class Datatype:
    __slots__ = ("cls", "version", "bits", "size", "props", "base")

    def __init__(self, cls: int, version: int, bits: int, size: int, props: bytes, base=None):
        self.cls = cls
        self.version = version
        self.bits = bits
        self.size = size
        self.props = props
        self.base = base

    def describe(self) -> str:
        names = {0: "int", 1: "float", 3: "string", 7: "reference", 9: "vlen", 6: "compound", 8: "enum"}
        return f"{names.get(self.cls, self.cls)}{self.size * 8}(bits=0x{self.bits:06x})"

    @property
    def little_endian(self) -> bool:
        return (self.bits & 0x1) == 0

    @property
    def signed(self) -> bool:
        return bool(self.bits & 0x8)

    @property
    def is_vlen_string(self) -> bool:
        return self.cls == 9 and (self.bits & 0xF) == 1


def parse_datatype(raw: bytes, off: int = 0) -> tuple[Datatype, int]:
    """Return (datatype, bytes consumed)."""
    head = raw[off]
    cls = head & 0x0F
    version = head >> 4
    bits = raw[off + 1] | (raw[off + 2] << 8) | (raw[off + 3] << 16)
    size = _u32(raw, off + 4)
    cursor = off + 8
    if cls == 0:  # fixed point: offset u16, precision u16
        props = bytes(raw[cursor : cursor + 4])
        cursor += 4
        return Datatype(cls, version, bits, size, props), cursor - off
    if cls == 1:  # float: offset, precision, exp loc, exp size, mant loc, mant size, bias
        props = bytes(raw[cursor : cursor + 12])
        cursor += 12
        return Datatype(cls, version, bits, size, props), cursor - off
    if cls == 3:  # fixed-length string, no properties
        return Datatype(cls, version, bits, size, b""), cursor - off
    if cls == 7:  # reference, no properties
        return Datatype(cls, version, bits, size, b""), cursor - off
    if cls == 9:  # variable length: base type follows
        base, used = parse_datatype(raw, cursor)
        cursor += used
        return Datatype(cls, version, bits, size, b"", base), cursor - off
    raise H5Error(f"unsupported datatype class {cls}")


def parse_dataspace(raw: bytes, off: int = 0) -> tuple[tuple[int, ...] | None, tuple[int, ...] | None]:
    """Return (dims, maxdims); dims None means a null dataspace; () is scalar."""
    version = raw[off]
    rank = raw[off + 1]
    flags = raw[off + 2]
    if version == 1:
        cursor = off + 8
        kind = 1 if rank else 0
    elif version == 2:
        kind = raw[off + 3]
        cursor = off + 4
    else:
        raise H5Error(f"unsupported dataspace version {version}")
    if kind == 2:
        return None, None
    dims = struct.unpack_from("<" + "Q" * rank, raw, cursor) if rank else ()
    cursor += 8 * rank
    maxdims = None
    if flags & 1:
        maxdims = struct.unpack_from("<" + "Q" * rank, raw, cursor)
    return tuple(dims), (tuple(maxdims) if maxdims is not None else None)


class H5File:
    def __init__(self, raw) -> None:
        self.raw = raw
        self.size = len(raw)
        self._gcol_cache: dict[int, dict[int, bytes]] = {}
        if bytes(raw[:8]) != SIGNATURE:
            raise H5Error("missing HDF5 signature at offset 0")
        version = raw[8]
        if version != 0:
            raise H5Error(f"unsupported superblock version {version}")
        if raw[13] != 8 or raw[14] != 8:
            raise H5Error("expected 8-byte offsets and lengths")
        base = _u64(raw, 24)
        if base != 0:
            raise H5Error("nonzero base address")
        self.eof = _u64(raw, 40)
        if self.eof != self.size:
            raise H5Error(f"superblock end-of-file {self.eof} != file size {self.size}")
        # root group symbol table entry at 56: name off, header addr, cache type, reserved, scratch
        self.root_header = _u64(raw, 64)
        self._check_addr(self.root_header, 16, "root object header")

    # -- low level -----------------------------------------------------------------
    def _check_addr(self, addr: int, length: int, what: str) -> None:
        if addr == UNDEF:
            raise H5Error(f"{what}: undefined address")
        if addr < 0 or addr + length > self.size:
            raise H5Error(f"{what}: address {addr}+{length} outside file of {self.size} bytes")

    def messages(self, addr: int) -> list[tuple[int, int, bytes]]:
        """All messages of a v1 object header as (type, flags, payload)."""
        raw = self.raw
        self._check_addr(addr, 16, "object header")
        if raw[addr] != 1:
            raise H5Error(f"unsupported object header version {raw[addr]} at {addr}")
        total = _u16(raw, addr + 2)
        header_size = _u32(raw, addr + 8)
        blocks = [(addr + 16, header_size)]
        found: list[tuple[int, int, bytes]] = []
        seen_blocks = set()
        while blocks:
            start, length = blocks.pop(0)
            if (start, length) in seen_blocks:
                raise H5Error("cyclic object header continuation")
            seen_blocks.add((start, length))
            self._check_addr(start, length, "object header block")
            cursor = start
            end = start + length
            while cursor + 8 <= end and len(found) < total:
                mtype = _u16(raw, cursor)
                msize = _u16(raw, cursor + 2)
                mflags = raw[cursor + 4]
                payload_start = cursor + 8
                payload_end = payload_start + msize
                if payload_end > end:
                    raise H5Error(f"object header message overruns block at {cursor}")
                payload = bytes(raw[payload_start:payload_end])
                found.append((mtype, mflags, payload))
                if mtype == MSG_CONTINUATION:
                    blocks.append((_u64(payload, 0), _u64(payload, 8)))
                cursor = payload_end
        if len(found) != total:
            raise H5Error(f"object header at {addr}: found {len(found)} of {total} messages")
        return found

    def _local_heap(self, addr: int) -> tuple[int, int]:
        raw = self.raw
        self._check_addr(addr, 32, "local heap")
        if bytes(raw[addr : addr + 4]) != b"HEAP" or raw[addr + 4] != 0:
            raise H5Error(f"bad local heap at {addr}")
        data_size = _u64(raw, addr + 8)
        data_addr = _u64(raw, addr + 24)
        self._check_addr(data_addr, data_size, "local heap data")
        return data_addr, data_size

    def _heap_string(self, data_addr: int, data_size: int, offset: int) -> str:
        if offset >= data_size:
            raise H5Error("local heap offset out of range")
        start = data_addr + offset
        end = self.raw.find(b"\0", start, data_addr + data_size)
        if end < 0:
            raise H5Error("unterminated local heap string")
        return bytes(self.raw[start:end]).decode("utf-8")

    def _group_btree(self, addr: int, heap: tuple[int, int], out: dict, depth: int = 0) -> None:
        raw = self.raw
        if depth > 32:
            raise H5Error("group B-tree too deep")
        self._check_addr(addr, 24, "group B-tree node")
        if bytes(raw[addr : addr + 4]) != b"TREE" or raw[addr + 4] != 0:
            raise H5Error(f"bad group B-tree node at {addr}")
        level = raw[addr + 5]
        entries = _u16(raw, addr + 6)
        cursor = addr + 24
        # key0, child0, key1, child1, ... keyN  (keys are 8-byte heap offsets)
        for index in range(entries):
            child = _u64(raw, cursor + 8 + index * 16)
            if level > 0:
                self._group_btree(child, heap, out, depth + 1)
            else:
                self._snod(child, heap, out)

    def _snod(self, addr: int, heap: tuple[int, int], out: dict) -> None:
        raw = self.raw
        self._check_addr(addr, 8, "symbol table node")
        if bytes(raw[addr : addr + 4]) != b"SNOD" or raw[addr + 4] != 1:
            raise H5Error(f"bad symbol table node at {addr}")
        count = _u16(raw, addr + 6)
        self._check_addr(addr + 8, count * 40, "symbol table entries")
        for index in range(count):
            entry = addr + 8 + index * 40
            name = self._heap_string(heap[0], heap[1], _u64(raw, entry))
            header = _u64(raw, entry + 8)
            cache_type = _u32(raw, entry + 16)
            if name in out:
                raise H5Error(f"duplicate link name {name!r}")
            if cache_type == 2:
                link_off = _u32(raw, entry + 24)
                out[name] = ("soft", self._heap_string(heap[0], heap[1], link_off))
            else:
                out[name] = ("hard", header)

    def links(self, addr: int) -> dict[str, tuple[str, object]]:
        """Group members: name -> ('hard', header_addr) or ('soft', path)."""
        msgs = self.messages(addr)
        out: dict[str, tuple[str, object]] = {}
        symtab = [p for t, _f, p in msgs if t == MSG_SYMBOL_TABLE]
        if symtab:
            if len(symtab) != 1:
                raise H5Error("multiple symbol table messages")
            btree = _u64(symtab[0], 0)
            heap = self._local_heap(_u64(symtab[0], 8))
            self._group_btree(btree, heap, out)
        for mtype, _flags, payload in msgs:
            if mtype == MSG_LINK:
                name, target = self._parse_link(payload)
                if name in out:
                    raise H5Error(f"duplicate link name {name!r}")
                out[name] = target
            elif mtype == MSG_LINK_INFO:
                fheap = _u64(payload, 2 + (8 if payload[1] & 1 else 0))
                if fheap != UNDEF:
                    raise H5Error("dense (fractal heap) group storage is unsupported")
        return out

    def _parse_link(self, p: bytes) -> tuple[str, tuple[str, object]]:
        if p[0] != 1:
            raise H5Error("unsupported link message version")
        flags = p[1]
        cursor = 2
        link_type = 0
        if flags & 0x08:
            link_type = p[cursor]
            cursor += 1
        if flags & 0x04:
            cursor += 8
        if flags & 0x10:
            cursor += 1
        size_len = 1 << (flags & 3)
        name_len = int.from_bytes(p[cursor : cursor + size_len], "little")
        cursor += size_len
        name = p[cursor : cursor + name_len].decode("utf-8")
        cursor += name_len
        if link_type == 0:
            return name, ("hard", _u64(p, cursor))
        if link_type == 1:
            length = _u16(p, cursor)
            return name, ("soft", p[cursor + 2 : cursor + 2 + length].decode("utf-8"))
        return name, ("external", None)

    # -- attributes --------------------------------------------------------------------
    def _gcol(self, addr: int) -> dict[int, bytes]:
        if addr in self._gcol_cache:
            return self._gcol_cache[addr]
        raw = self.raw
        self._check_addr(addr, 16, "global heap collection")
        if bytes(raw[addr : addr + 4]) != b"GCOL" or raw[addr + 4] != 1:
            raise H5Error(f"bad global heap collection at {addr}")
        size = _u64(raw, addr + 8)
        self._check_addr(addr, size, "global heap collection body")
        objects: dict[int, bytes] = {}
        cursor = addr + 16
        end = addr + size
        while cursor + 16 <= end:
            index = _u16(raw, cursor)
            osize = _u64(raw, cursor + 8)
            if index == 0:
                break
            objects[index] = bytes(raw[cursor + 16 : cursor + 16 + osize])
            cursor += 16 + _pad8(osize)
        self._gcol_cache[addr] = objects
        return objects

    def _decode_values(self, dtype: Datatype, count: int, data: bytes):
        values = []
        for i in range(count):
            chunk = data[i * dtype.size : (i + 1) * dtype.size]
            if dtype.cls == 0:
                values.append(int.from_bytes(chunk, "little" if dtype.little_endian else "big", signed=dtype.signed))
            elif dtype.cls == 1:
                fmt = {4: "f", 8: "d"}.get(dtype.size)
                if fmt is None:
                    raise H5Error(f"unsupported float size {dtype.size}")
                values.append(struct.unpack(("<" if dtype.little_endian else ">") + fmt, chunk)[0])
            elif dtype.cls == 3:
                values.append(chunk.split(b"\0", 1)[0].decode("utf-8", "replace").rstrip(" "))
            elif dtype.is_vlen_string:
                length = _u32(chunk, 0)
                coll = _u64(chunk, 4)
                index = _u32(chunk, 12)
                if length == 0 or coll == 0 or coll == UNDEF:
                    values.append("")
                else:
                    obj = self._gcol(coll).get(index)
                    if obj is None:
                        raise H5Error(f"missing global heap object {coll}:{index}")
                    values.append(obj[:length].decode("utf-8", "replace"))
            else:
                values.append(None)
        return values

    def attributes(self, addr: int, msgs=None) -> dict[str, object]:
        if msgs is None:
            msgs = self.messages(addr)
        out: dict[str, object] = {}
        for mtype, _flags, p in msgs:
            if mtype == MSG_ATTRIBUTE_INFO:
                fheap = _u64(p, 2 + (2 if p[1] & 1 else 0))
                if fheap != UNDEF:
                    raise H5Error("dense attribute storage is unsupported")
            if mtype != MSG_ATTRIBUTE:
                continue
            version = p[0]
            name_size = _u16(p, 2)
            dt_size = _u16(p, 4)
            ds_size = _u16(p, 6)
            if version == 1:
                cursor = 8
                name = p[cursor : cursor + name_size].split(b"\0", 1)[0].decode("utf-8")
                cursor += _pad8(name_size)
                dtype, _ = parse_datatype(p, cursor)
                cursor += _pad8(dt_size)
                dims, _ = parse_dataspace(p, cursor)
                cursor += _pad8(ds_size)
            elif version in (2, 3):
                cursor = 8 if version == 2 else 9
                name = p[cursor : cursor + name_size].split(b"\0", 1)[0].decode("utf-8")
                cursor += name_size
                dtype, _ = parse_datatype(p, cursor)
                cursor += dt_size
                dims, _ = parse_dataspace(p, cursor)
                cursor += ds_size
            else:
                raise H5Error(f"unsupported attribute message version {version}")
            if dims is None:
                out[name] = None
                continue
            count = 1
            for d in dims:
                count *= d
            values = self._decode_values(dtype, count, p[cursor : cursor + count * dtype.size])
            out[name] = values[0] if dims == () else values
        return out

    # -- datasets ------------------------------------------------------------------------
    def dataset_info(self, addr: int, msgs=None) -> dict[str, object]:
        if msgs is None:
            msgs = self.messages(addr)
        info: dict[str, object] = {"filters": []}
        for mtype, _flags, p in msgs:
            if mtype == MSG_DATASPACE:
                info["dims"], info["maxdims"] = parse_dataspace(p)
            elif mtype == MSG_DATATYPE:
                info["dtype"], _ = parse_datatype(p)
            elif mtype == MSG_LAYOUT:
                info["layout"] = self._parse_layout(p)
            elif mtype == MSG_FILTERS:
                info["filters"] = self._parse_filters(p)
        if "dims" not in info or "dtype" not in info or "layout" not in info:
            raise H5Error(f"object at {addr} is not a dataset")
        return info

    @staticmethod
    def _parse_layout(p: bytes) -> dict[str, object]:
        if p[0] != 3:
            raise H5Error(f"unsupported layout message version {p[0]}")
        cls = p[1]
        if cls == 0:
            size = _u16(p, 2)
            return {"class": "compact", "data": p[4 : 4 + size]}
        if cls == 1:
            return {"class": "contiguous", "address": _u64(p, 2), "size": _u64(p, 10)}
        if cls == 2:
            ndims = p[2]
            btree = _u64(p, 3)
            dims = struct.unpack_from("<" + "I" * ndims, p, 11)
            return {"class": "chunked", "btree": btree, "chunk": tuple(dims[:-1]), "element_size": dims[-1]}
        raise H5Error(f"unsupported layout class {cls}")

    @staticmethod
    def _parse_filters(p: bytes) -> list[tuple[int, tuple[int, ...]]]:
        version = p[0]
        count = p[1]
        out = []
        if version == 1:
            cursor = 8
            for _ in range(count):
                fid = _u16(p, cursor)
                name_len = _u16(p, cursor + 2)
                nvals = _u16(p, cursor + 6)
                cursor += 8 + _pad8(name_len)
                vals = struct.unpack_from("<" + "I" * nvals, p, cursor)
                cursor += 4 * nvals + (4 if nvals % 2 else 0)
                out.append((fid, tuple(vals)))
        elif version == 2:
            cursor = 2
            for _ in range(count):
                fid = _u16(p, cursor)
                cursor += 2
                name_len = 0
                if fid >= 256:
                    name_len = _u16(p, cursor)
                    cursor += 2
                nvals = _u16(p, cursor + 2)
                cursor += 4 + name_len
                vals = struct.unpack_from("<" + "I" * nvals, p, cursor)
                cursor += 4 * nvals
                out.append((fid, tuple(vals)))
        else:
            raise H5Error(f"unsupported filter pipeline version {version}")
        return out

    def chunk_index(self, btree: int, rank: int) -> list[tuple[tuple[int, ...], int, int, int]]:
        """Leaf entries of a v1 chunk B-tree: (offsets, address, stored_bytes, filter_mask)."""
        raw = self.raw
        key_size = 8 + 8 * (rank + 1)
        out = []
        visited = set()

        def visit(addr: int, expected_level, depth: int) -> None:
            if addr in visited:
                raise H5Error("cyclic chunk B-tree")
            visited.add(addr)
            if depth > 64:
                raise H5Error("chunk B-tree too deep")
            self._check_addr(addr, 24, "chunk B-tree node")
            if bytes(raw[addr : addr + 4]) != b"TREE" or raw[addr + 4] != 1:
                raise H5Error(f"bad chunk B-tree node at {addr}")
            level = raw[addr + 5]
            if expected_level is not None and level != expected_level:
                raise H5Error("chunk B-tree level mismatch")
            entries = _u16(raw, addr + 6)
            self._check_addr(addr + 24, entries * (key_size + 8) + key_size, "chunk B-tree entries")
            cursor = addr + 24
            for _ in range(entries):
                stored = _u32(raw, cursor)
                mask = _u32(raw, cursor + 4)
                offsets = struct.unpack("<" + "Q" * (rank + 1), raw[cursor + 8 : cursor + 8 + 8 * (rank + 1)])
                child = _u64(raw, cursor + key_size)
                if level > 0:
                    visit(child, level - 1, depth + 1)
                else:
                    if offsets[-1] != 0:
                        raise H5Error("nonzero element-axis chunk offset")
                    self._check_addr(child, stored, "chunk data")
                    out.append((tuple(offsets[:-1]), child, stored, mask))
                cursor += key_size + 8

        if btree == UNDEF:
            return out
        visit(btree, None, 0)
        out.sort()
        return out

    def read_1d(self, info: dict[str, object]) -> tuple[bytes, dict[str, object]]:
        """Raw little-endian element bytes of a rank-1 dataset plus decode stats."""
        dims = info["dims"]
        dtype: Datatype = info["dtype"]
        layout = info["layout"]
        if dims is None or len(dims) != 1:
            raise H5Error(f"expected rank-1 dataset, got dims={dims}")
        n = dims[0]
        esize = dtype.size
        total = n * esize
        stats = {"chunks": 0, "stored_bytes": 0, "layout": layout["class"]}
        if layout["class"] == "contiguous":
            if info["filters"]:
                raise H5Error("filters on contiguous dataset")
            addr = layout["address"]
            if n == 0:
                return b"", stats
            self._check_addr(addr, total, "contiguous data")
            stats["stored_bytes"] = total
            return bytes(self.raw[addr : addr + total]), stats
        if layout["class"] == "compact":
            data = layout["data"]
            if len(data) < total:
                raise H5Error("compact data too short")
            return bytes(data[:total]), stats
        if layout["element_size"] != esize or len(layout["chunk"]) != 1:
            raise H5Error("chunk layout does not match datatype/rank")
        chunk_len = layout["chunk"][0]
        chunk_bytes = chunk_len * esize
        filters = info["filters"]
        for fid, _vals in filters:
            if fid not in (FILTER_DEFLATE, FILTER_SHUFFLE):
                raise H5Error(f"unsupported filter id {fid}")
        entries = self.chunk_index(layout["btree"], 1)
        expected = list(range(0, n, chunk_len))
        if [e[0][0] for e in entries] != expected:
            raise H5Error(f"chunk grid mismatch: {len(entries)} chunks for {n} values / {chunk_len}")
        out = bytearray(total)
        for (offset,), addr, stored, mask in entries:
            data = bytes(self.raw[addr : addr + stored])
            for index in range(len(filters) - 1, -1, -1):
                if mask & (1 << index):
                    continue
                fid, vals = filters[index]
                if fid == FILTER_DEFLATE:
                    data = zlib.decompress(data)
                elif fid == FILTER_SHUFFLE:
                    size = vals[0] if vals else esize
                    if size != esize:
                        raise H5Error(f"shuffle element size {size} != {esize}")
                    data = unshuffle(data, size)
            if len(data) != chunk_bytes:
                raise H5Error(f"decoded chunk size {len(data)} != {chunk_bytes}")
            start = offset * esize
            take = min(chunk_bytes, total - start)
            out[start : start + take] = data[:take]
            stats["chunks"] += 1
            stats["stored_bytes"] += stored
        stats["filter_ids"] = [fid for fid, _ in filters]
        return bytes(out), stats
