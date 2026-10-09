#!/usr/bin/env python3
"""Pure-standard-library HDF5 reader for SXS (SpEC / scri.SpEC) waveform files.

Scope is intentionally narrow and anything outside it raises ``H5Error``:

* superblock version 0 with 8-byte offsets and lengths, base address 0
* version-1 object headers (with continuation blocks)
* "old style" symbol-table groups: Symbol Table message (0x11), version-1
  B-tree node type 0, symbol-table nodes (``SNOD``) and local heaps (``HEAP``)
* Dataspace (v1/v2), Datatype (fixed point / IEEE float, little-endian),
  Filter Pipeline (v1/v2) and Data Layout version 3 messages
* contiguous datasets without filters and chunked datasets indexed by a
  version-1 B-tree (node type 1)
* filters: deflate (id 1) and byte shuffle (id 2), applied in pipeline order
  at write time and undone in reverse order at read time

``raw`` may be any object supporting ``len()`` and contiguous slicing that
returns ``bytes`` (``bytes``, ``mmap.mmap`` or the probe's remote block store).
"""
from __future__ import annotations

import struct
import zlib

UNDEF = 0xFFFFFFFFFFFFFFFF
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"

MSG_NIL = 0x00
MSG_DATASPACE = 0x01
MSG_DATATYPE = 0x03
MSG_FILL_OLD = 0x04
MSG_FILL = 0x05
MSG_LAYOUT = 0x08
MSG_FILTERS = 0x0B
MSG_ATTRIBUTE = 0x0C
MSG_CONTINUATION = 0x10
MSG_SYMBOL_TABLE = 0x11

FILTER_DEFLATE = 1
FILTER_SHUFFLE = 2


class H5Error(ValueError):
    """Malformed or out-of-scope HDF5 structure."""


def _pad8(n: int) -> int:
    return (n + 7) & ~7


class H5File:
    def __init__(self, raw, expected_size: int | None = None) -> None:
        self.raw = raw
        self.size = len(raw)
        if expected_size is not None and self.size != expected_size:
            raise H5Error(f"file size {self.size} != expected {expected_size}")
        head = self.read(0, 96)
        if head[:8] != HDF5_SIGNATURE:
            raise H5Error("missing HDF5 signature")
        if head[8] != 0:
            raise H5Error(f"superblock version {head[8]} is out of scope (want 0)")
        fs_ver, root_ver, _r1, sh_ver, so, sl, _r2 = struct.unpack_from("<7B", head, 9)
        if (fs_ver, root_ver, sh_ver, so, sl) != (0, 0, 0, 8, 8):
            raise H5Error("unexpected superblock v0 field values")
        self.leaf_k, self.internal_k = struct.unpack_from("<HH", head, 16)
        _flags = struct.unpack_from("<I", head, 20)[0]
        base, _free, eof, _driver = struct.unpack_from("<4Q", head, 24)
        if base != 0:
            raise H5Error("nonzero base address")
        if eof > self.size:
            raise H5Error(f"superblock end-of-file {eof} exceeds file size {self.size}")
        self.eof = eof
        # root group symbol table entry at offset 56
        _name_off, self.root_addr, cache_type, _res = struct.unpack_from("<QQII", head, 56)
        self.root_cache_type = cache_type

    # ----------------------------------------------------------------- utils
    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self.size or offset == UNDEF:
            raise H5Error(f"read {offset}+{length} outside file of {self.size} bytes")
        data = bytes(self.raw[offset:offset + length])
        if len(data) != length:
            raise H5Error("short read")
        return data

    # -------------------------------------------------------- object headers
    def messages(self, addr: int) -> list[tuple[int, int, bytes]]:
        head = self.read(addr, 16)
        version, _res, nmsgs, _refc, hsize = struct.unpack_from("<BBHII", head, 0)
        if version != 1:
            raise H5Error(f"object header version {version} at {addr} is out of scope (want 1)")
        blocks = [(addr + 16, hsize)]
        seen = {addr}
        out: list[tuple[int, int, bytes]] = []
        count = 0
        while blocks:
            start, length = blocks.pop(0)
            block = self.read(start, length)
            pos = 0
            while pos + 8 <= length:
                mtype, msize, mflags = struct.unpack_from("<HHB", block, pos)
                pos += 8
                if pos + msize > length:
                    raise H5Error("object header message exceeds its block")
                payload = block[pos:pos + msize]
                pos += msize
                count += 1
                if mtype == MSG_CONTINUATION:
                    caddr, clen = struct.unpack_from("<QQ", payload, 0)
                    if caddr in seen:
                        raise H5Error("object header continuation loop")
                    seen.add(caddr)
                    blocks.append((caddr, clen))
                elif mtype != MSG_NIL:
                    out.append((mtype, mflags, payload))
        if count != nmsgs:
            raise H5Error(f"object header at {addr}: parsed {count} messages, header says {nmsgs}")
        return out

    @staticmethod
    def single(messages, mtype: int) -> bytes:
        found = [(f, p) for t, f, p in messages if t == mtype]
        if len(found) != 1:
            raise H5Error(f"expected one message of type {mtype:#x}, found {len(found)}")
        flags, payload = found[0]
        if flags & 0x02:
            raise H5Error(f"shared message type {mtype:#x} is out of scope")
        return payload

    # ---------------------------------------------------------------- groups
    def _local_heap(self, addr: int) -> bytes:
        head = self.read(addr, 32)
        if head[:4] != b"HEAP" or head[4] != 0:
            raise H5Error(f"missing local heap at {addr}")
        data_size, _free, data_addr = struct.unpack_from("<QQQ", head, 8)
        return self.read(data_addr, data_size)

    @staticmethod
    def _heap_string(heap: bytes, offset: int) -> str:
        if offset >= len(heap):
            raise H5Error("local heap name offset out of range")
        end = heap.find(b"\x00", offset)
        if end < 0:
            raise H5Error("unterminated local heap name")
        return heap[offset:end].decode("utf-8")

    def group_links(self, header_addr: int, defer: tuple = (), deferred: list | None = None) -> dict[str, int]:
        """Links of a symbol-table group.

        Exceptions of the types in ``defer`` raised while reading a leaf
        symbol-table node are appended to ``deferred`` and the walk continues,
        so a planner can learn every missing node in one pass; the caller must
        treat a non-empty ``deferred`` as an incomplete result.
        """
        msgs = self.messages(header_addr)
        stab = self.single(msgs, MSG_SYMBOL_TABLE)
        btree, heap_addr = struct.unpack_from("<QQ", stab, 0)
        heap = self._local_heap(heap_addr)
        links: dict[str, int] = {}

        def visit(node: int, expected_level: int | None, depth: int) -> None:
            if depth > 32:
                raise H5Error("group B-tree too deep")
            head = self.read(node, 24)
            if head[:4] != b"TREE" or head[4] != 0:
                raise H5Error(f"expected group B-tree node at {node}")
            level = head[5]
            used = struct.unpack_from("<H", head, 6)[0]
            if expected_level is not None and level != expected_level:
                raise H5Error("group B-tree level mismatch")
            body = self.read(node + 24, 8 + used * 16)
            for i in range(used):
                child = struct.unpack_from("<Q", body, 8 + 16 * i)[0]
                if level > 0:
                    visit(child, level - 1, depth + 1)
                    continue
                try:
                    snod = self.read(child, 8)
                    if snod[:4] != b"SNOD" or snod[4] != 1:
                        raise H5Error(f"expected SNOD v1 at {child}")
                    nsym = struct.unpack_from("<H", snod, 6)[0]
                    entries = self.read(child + 8, 40 * nsym)
                except defer as exc:  # type: ignore[misc]
                    if deferred is None:
                        raise
                    deferred.append(exc)
                    continue
                for j in range(nsym):
                    name_off, obj_addr = struct.unpack_from("<QQ", entries, 40 * j)
                    name = self._heap_string(heap, name_off)
                    if name in links:
                        raise H5Error(f"duplicate link {name!r}")
                    links[name] = obj_addr

        visit(btree, None, 0)
        return links

    def attributes(self, header_addr: int) -> dict[str, object]:
        """Version-1 attribute messages with simple numeric or fixed-string values."""
        out: dict[str, object] = {}
        for mtype, _flags, payload in self.messages(header_addr):
            if mtype != MSG_ATTRIBUTE:
                continue
            if payload[0] != 1:
                raise H5Error(f"attribute message version {payload[0]} out of scope")
            name_size, type_size, space_size = struct.unpack_from("<HHH", payload, 2)
            pos = 8
            name = payload[pos:pos + name_size].split(b"\x00", 1)[0].decode("utf-8")
            pos += _pad8(name_size)
            dt_raw = payload[pos:pos + type_size]
            pos += _pad8(type_size)
            sp_raw = payload[pos:pos + space_size]
            pos += _pad8(space_size)
            if sp_raw[0] == 1 and sp_raw[1] == 0:
                dims: tuple[int, ...] = ()
            else:
                dims = decode_dataspace(sp_raw)
            count = 1
            for d in dims:
                count *= d
            try:
                dt = decode_datatype(dt_raw)
            except H5Error:
                out[name] = None
                continue
            if dt["kind"] == "string":
                out[name] = payload[pos:pos + dt["size"] * count].split(b"\x00", 1)[0].decode("utf-8", "replace")
            else:
                out[name] = list(struct.unpack_from(f"<{count}{dt['code']}", payload, pos))
        return out

    def is_group(self, header_addr: int) -> bool:
        return any(t == MSG_SYMBOL_TABLE for t, _f, _p in self.messages(header_addr))

    def resolve(self, path: str) -> int:
        addr = self.root_addr
        for part in [p for p in path.split("/") if p]:
            links = self.group_links(addr)
            if part not in links:
                raise H5Error(f"path component {part!r} not found")
            addr = links[part]
        return addr

    # -------------------------------------------------------------- datasets
    def dataset(self, header_addr: int) -> dict:
        msgs = self.messages(header_addr)
        shape = decode_dataspace(self.single(msgs, MSG_DATASPACE))
        dtype = decode_datatype(self.single(msgs, MSG_DATATYPE))
        layout = self.single(msgs, MSG_LAYOUT)
        filt = [p for t, _f, p in msgs if t == MSG_FILTERS]
        if len(filt) > 1:
            raise H5Error("multiple filter pipeline messages")
        filters = decode_filters(filt[0]) if filt else []
        info = {"shape": shape, "dtype": dtype, "filters": filters}
        if layout[0] != 3:
            raise H5Error(f"data layout version {layout[0]} is out of scope")
        cls = layout[1]
        info["layout_class"] = cls
        if cls == 1:
            info["data_addr"], info["data_size"] = struct.unpack_from("<QQ", layout, 2)
            if filters:
                raise H5Error("filtered contiguous dataset is out of scope")
        elif cls == 2:
            ndims = layout[2]
            info["chunk_btree"] = struct.unpack_from("<Q", layout, 3)[0]
            dims = struct.unpack_from(f"<{ndims}I", layout, 11)
            if ndims != len(shape) + 1 or dims[-1] != dtype["size"]:
                raise H5Error("chunk dimensionality / element size mismatch")
            info["chunk_dims"] = tuple(dims[:-1])
        else:
            raise H5Error(f"layout class {cls} is out of scope")
        return info

    def chunk_entries(self, btree: int, rank: int) -> list[tuple[int, int, tuple[int, ...], int]]:
        """(stored size, filter mask, chunk offsets, address) for every chunk."""
        out: list[tuple[int, int, tuple[int, ...], int]] = []
        key_size = 8 + 8 * (rank + 1)

        def visit(node: int, expected_level: int | None, depth: int) -> None:
            if depth > 32:
                raise H5Error("chunk B-tree too deep")
            head = self.read(node, 24)
            if head[:4] != b"TREE" or head[4] != 1:
                raise H5Error(f"expected raw-data chunk B-tree node at {node}")
            level = head[5]
            used = struct.unpack_from("<H", head, 6)[0]
            if expected_level is not None and level != expected_level:
                raise H5Error("chunk B-tree level mismatch")
            body = self.read(node + 24, used * (key_size + 8) + key_size)
            pos = 0
            for _ in range(used):
                size, mask = struct.unpack_from("<II", body, pos)
                offsets = struct.unpack_from(f"<{rank + 1}Q", body, pos + 8)
                child = struct.unpack_from("<Q", body, pos + key_size)[0]
                pos += key_size + 8
                if level == 0:
                    if offsets[-1] != 0:
                        raise H5Error("nonzero element-size chunk offset")
                    out.append((size, mask, tuple(offsets[:-1]), child))
                else:
                    visit(child, level - 1, depth + 1)

        visit(btree, None, 0)
        return out

    def read_array_bytes(self, info: dict) -> bytes:
        """Logical row-major little-endian bytes of a whole 1-D or 2-D dataset."""
        shape = info["shape"]
        esize = info["dtype"]["size"]
        total = esize
        for d in shape:
            total *= d
        if info["layout_class"] == 1:
            if info["data_size"] != total:
                raise H5Error("contiguous data size mismatch")
            return self.read(info["data_addr"], total)
        rank = len(shape)
        if rank not in (1, 2):
            raise H5Error("only rank-1/2 chunked datasets are supported")
        cdims = info["chunk_dims"]
        chunk_elems = 1
        for d in cdims:
            chunk_elems *= d
        chunk_bytes = chunk_elems * esize
        out = bytearray(total)
        seen: set[tuple[int, ...]] = set()
        entries = self.chunk_entries(info["chunk_btree"], rank)
        for size, mask, offsets, addr in entries:
            if offsets in seen:
                raise H5Error(f"duplicate chunk {offsets}")
            seen.add(offsets)
            if any(o % c for o, c in zip(offsets, cdims)) or any(o >= s for o, s in zip(offsets, shape)):
                raise H5Error(f"misaligned or out-of-range chunk {offsets}")
            data = decode_chunk(self.read(addr, size), info["filters"], mask, esize, chunk_bytes)
            if rank == 1:
                n = min(cdims[0], shape[0] - offsets[0])
                out[offsets[0] * esize:(offsets[0] + n) * esize] = data[:n * esize]
            else:
                r0, c0 = offsets
                nr = min(cdims[0], shape[0] - r0)
                nc = min(cdims[1], shape[1] - c0)
                row_bytes = nc * esize
                for r in range(nr):
                    src = r * cdims[1] * esize
                    dst = ((r0 + r) * shape[1] + c0) * esize
                    out[dst:dst + row_bytes] = data[src:src + row_bytes]
        expected = 1
        for s, c in zip(shape, cdims):
            expected *= -(-s // c)
        if len(seen) != expected:
            raise H5Error(f"chunk count {len(seen)} != expected {expected}")
        return bytes(out)


def unshuffle(data: bytes, element_size: int) -> bytes:
    if element_size <= 1:
        return bytes(data)
    count = len(data) // element_size
    body = count * element_size
    out = bytearray(len(data))
    for b in range(element_size):
        out[b:body:element_size] = data[b * count:(b + 1) * count]
    out[body:] = data[body:]
    return bytes(out)


def shuffle(data: bytes, element_size: int) -> bytes:
    """Forward shuffle (self-test only)."""
    if element_size <= 1:
        return bytes(data)
    count = len(data) // element_size
    body = count * element_size
    out = bytearray()
    for b in range(element_size):
        out += data[b:body:element_size]
    out += data[body:]
    return bytes(out)


def decode_chunk(stored: bytes, filters, mask: int, element_size: int, expected_size: int) -> bytes:
    data = bytes(stored)
    for index in range(len(filters) - 1, -1, -1):
        filter_id, flags, values = filters[index]
        if mask & (1 << index):
            continue
        if filter_id == FILTER_DEFLATE:
            inflater = zlib.decompressobj()
            try:
                data = inflater.decompress(data)
            except zlib.error as exc:
                raise H5Error(f"deflate chunk failed to inflate: {exc}") from exc
            if not inflater.eof or inflater.unused_data:
                raise H5Error("deflate stream incomplete or followed by extra bytes")
        elif filter_id == FILTER_SHUFFLE:
            if values and values[0] != element_size:
                raise H5Error(f"shuffle element size {values[0]} != {element_size}")
            data = unshuffle(data, element_size)
        else:
            raise H5Error(f"filter {filter_id} is out of scope")
    if len(data) != expected_size:
        raise H5Error(f"decoded chunk has {len(data)} bytes, expected {expected_size}")
    return data


def decode_dataspace(payload: bytes) -> tuple[int, ...]:
    version, rank = payload[0], payload[1]
    if version == 1:
        pos = 8
    elif version == 2:
        if payload[3] != 1:
            raise H5Error("non-simple dataspace")
        pos = 4
    else:
        raise H5Error(f"dataspace version {version} out of scope")
    return tuple(struct.unpack_from(f"<{rank}Q", payload, pos))


def decode_datatype(payload: bytes) -> dict:
    cls = payload[0] & 0x0F
    bits = payload[1] | (payload[2] << 8) | (payload[3] << 16)
    size = struct.unpack_from("<I", payload, 4)[0]
    if cls == 1:
        if bits & 0x01 or bits & 0x40:
            raise H5Error("big-endian / VAX float out of scope")
        if size == 8:
            offset, precision, epos, esize, mpos, msize, bias = struct.unpack_from("<HHBBBBI", payload, 8)
            if (offset, precision, epos, esize, mpos, msize, bias) != (0, 64, 52, 11, 0, 52, 1023):
                raise H5Error("float64 datatype is not IEEE binary64")
            return {"kind": "float", "size": 8, "code": "d"}
        if size == 4:
            return {"kind": "float", "size": 4, "code": "f"}
        raise H5Error(f"float size {size} out of scope")
    if cls == 0:
        if bits & 0x01:
            raise H5Error("big-endian integer out of scope")
        signed = bool(bits & 0x08)
        code = {1: "b", 2: "h", 4: "i", 8: "q"}[size]
        return {"kind": "int" if signed else "uint", "size": size, "code": code if signed else code.upper()}
    if cls == 3:
        return {"kind": "string", "size": size, "code": None}
    raise H5Error(f"datatype class {cls} out of scope")


def decode_filters(payload: bytes) -> list[tuple[int, int, tuple[int, ...]]]:
    version, count = payload[0], payload[1]
    out = []
    if version == 1:
        pos = 8
        for _ in range(count):
            filter_id, name_len, flags, nvals = struct.unpack_from("<4H", payload, pos)
            pos += 8 + _pad8(name_len)
            values = struct.unpack_from(f"<{nvals}I", payload, pos)
            pos += 4 * nvals + (4 if nvals % 2 else 0)
            out.append((filter_id, flags, tuple(values)))
    elif version == 2:
        pos = 2
        for _ in range(count):
            filter_id = struct.unpack_from("<H", payload, pos)[0]
            pos += 2
            name_len = 0
            if filter_id >= 256:
                name_len = struct.unpack_from("<H", payload, pos)[0]
                pos += 2
            flags, nvals = struct.unpack_from("<HH", payload, pos)
            pos += 4 + name_len
            values = struct.unpack_from(f"<{nvals}I", payload, pos)
            pos += 4 * nvals
            out.append((filter_id, flags, tuple(values)))
    else:
        raise H5Error(f"filter pipeline version {version} out of scope")
    if pos > len(payload):
        raise H5Error("truncated filter pipeline")
    return out
