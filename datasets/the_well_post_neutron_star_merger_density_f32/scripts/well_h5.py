#!/usr/bin/env python3
"""Strict pure-stdlib reader for the metadata of The Well HDF5 files.

Only what the pinned post_neutron_star_merger files use is supported:
superblock version 2 (8-byte offsets/lengths, Jenkins lookup3 checksum), a
superblock-extension object header, version-1 object headers (with
continuation blocks), symbol-table groups (version-1 group B-trees, SNOD
nodes, version-0 local heaps), version-1/2 dataspaces, fixed-point/float/
string datatypes, version-3 layout messages and filter-pipeline messages.
Anything else raises H5Error instead of being guessed.

Reads go through `Sparse`, an absolute-offset view over the few byte ranges
that were fetched from a remote file, so the 14 GB files are never needed.
"""

from __future__ import annotations

import struct

HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
UNDEF = 0xFFFFFFFFFFFFFFFF

MSG_NIL = 0x0000
MSG_DATASPACE = 0x0001
MSG_LINK_INFO = 0x0002
MSG_DATATYPE = 0x0003
MSG_FILL_OLD = 0x0004
MSG_FILL = 0x0005
MSG_LINK = 0x0006
MSG_EXTERNAL = 0x0007
MSG_LAYOUT = 0x0008
MSG_GROUP_INFO = 0x000A
MSG_FILTER = 0x000B
MSG_ATTRIBUTE = 0x000C
MSG_MTIME_OLD = 0x000E
MSG_CONTINUATION = 0x0010
MSG_SYMBOL_TABLE = 0x0011
MSG_MTIME = 0x0012
MSG_ATTR_INFO = 0x0015
MSG_FSINFO = 0x0017

# H5T_IEEE_F32LE / F64LE datatype messages (class 1, version 1).
H5T_IEEE_F32LE = bytes.fromhex("11201f000400000000002000170800177f000000")
H5T_IEEE_F64LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")


class H5Error(ValueError):
    pass


# ---------------------------------------------------------------- checksum
def _rot(x: int, k: int) -> int:
    return ((x << k) | (x >> (32 - k))) & 0xFFFFFFFF


def lookup3(data: bytes, initval: int = 0) -> int:
    """Bob Jenkins' hashlittle (lookup3), as used by H5_checksum_lookup3."""
    length = len(data)
    a = b = c = (0xDEADBEEF + length + initval) & 0xFFFFFFFF
    M = 0xFFFFFFFF
    i = 0
    while length > 12:
        a = (a + int.from_bytes(data[i : i + 4], "little")) & M
        b = (b + int.from_bytes(data[i + 4 : i + 8], "little")) & M
        c = (c + int.from_bytes(data[i + 8 : i + 12], "little")) & M
        a = (a - c) & M; a ^= _rot(c, 4); c = (c + b) & M
        b = (b - a) & M; b ^= _rot(a, 6); a = (a + c) & M
        c = (c - b) & M; c ^= _rot(b, 8); b = (b + a) & M
        a = (a - c) & M; a ^= _rot(c, 16); c = (c + b) & M
        b = (b - a) & M; b ^= _rot(a, 19); a = (a + c) & M
        c = (c - b) & M; c ^= _rot(b, 4); b = (b + a) & M
        length -= 12
        i += 12
    if length == 0:
        return c
    tail = data[i:] + b"\0" * (12 - length)
    a = (a + int.from_bytes(tail[0:4], "little")) & M
    b = (b + int.from_bytes(tail[4:8], "little")) & M
    c = (c + int.from_bytes(tail[8:12], "little")) & M
    c ^= b; c = (c - _rot(b, 14)) & M
    a ^= c; a = (a - _rot(c, 11)) & M
    b ^= a; b = (b - _rot(a, 25)) & M
    c ^= b; c = (c - _rot(b, 16)) & M
    a ^= c; a = (a - _rot(c, 4)) & M
    b ^= a; b = (b - _rot(a, 14)) & M
    c ^= b; c = (c - _rot(b, 24)) & M
    return c


# -------------------------------------------------------------- byte view
class Sparse:
    """Absolute-offset view over fetched byte ranges of one remote file."""

    def __init__(self, segments: list[tuple[int, bytes]], file_size: int):
        self.segments = sorted((int(start), bytes(data)) for start, data in segments)
        self.size = int(file_size)

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self.size:
            raise H5Error(f"read {offset}+{length} outside file of {self.size} bytes")
        for start, data in self.segments:
            if start <= offset and offset + length <= start + len(data):
                return data[offset - start : offset - start + length]
        raise H5Error(f"bytes {offset}+{length} lie outside the fetched metadata ranges")

    def cstring(self, offset: int, limit: int) -> str:
        for start, data in self.segments:
            if start <= offset < start + len(data):
                end = data.find(b"\0", offset - start, offset - start + limit)
                if end < 0:
                    raise H5Error(f"unterminated string at {offset}")
                return data[offset - start : end].decode("utf-8")
        raise H5Error(f"string at {offset} lies outside the fetched metadata ranges")


def _u(fmt: str, payload: bytes, offset: int) -> int:
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(payload):
        raise H5Error("truncated HDF5 structure")
    return struct.unpack_from(fmt, payload, offset)[0]


def u8(p: bytes, o: int) -> int:
    return _u("<B", p, o)


def u16(p: bytes, o: int) -> int:
    return _u("<H", p, o)


def u32(p: bytes, o: int) -> int:
    return _u("<I", p, o)


def u64(p: bytes, o: int) -> int:
    return _u("<Q", p, o)


def pad8(n: int) -> int:
    return (n + 7) & ~7


# ------------------------------------------------------------------ file
class H5:
    def __init__(self, view: Sparse):
        self.v = view
        head = view.read(0, 48)
        if head[:8] != HDF5_SIGNATURE:
            raise H5Error("missing HDF5 signature at offset 0")
        self.superblock_version = head[8]
        if self.superblock_version not in (2, 3):
            raise H5Error(f"unsupported superblock version {self.superblock_version}")
        if head[9] != 8 or head[10] != 8:
            raise H5Error("expected 8-byte offsets and lengths")
        self.consistency_flags = head[11]
        self.base_address = u64(head, 12)
        self.extension_address = u64(head, 20)
        self.eof_address = u64(head, 28)
        self.root_header = u64(head, 36)
        stored = u32(head, 44)
        computed = lookup3(head[:44])
        if stored != computed:
            raise H5Error(f"superblock checksum mismatch stored={stored:08x} computed={computed:08x}")
        if self.base_address != 0:
            raise H5Error(f"nonzero base address {self.base_address}")
        if self.eof_address != view.size:
            raise H5Error(f"superblock EOF address {self.eof_address} != file size {view.size}")

    # ------------------------------------------------------ object headers
    def messages(self, address: int) -> list[tuple[int, int, bytes]]:
        prefix = self.v.read(address, 16)
        if prefix[:4] == b"OHDR":
            raise H5Error(f"version-2 object header at {address} is out of scope")
        if prefix[0] != 1 or prefix[1] != 0:
            raise H5Error(f"unsupported object header prefix at {address}: {prefix[:2].hex()}")
        declared = u16(prefix, 2)
        blocks = [(address + 16, u32(prefix, 8))]
        seen: set[int] = set()
        found: list[tuple[int, int, bytes]] = []
        while blocks:
            start, length = blocks.pop(0)
            if start in seen:
                raise H5Error(f"cyclic continuation at {start}")
            seen.add(start)
            block = self.v.read(start, length)
            cursor = 0
            while cursor + 8 <= length:
                mtype = u16(block, cursor)
                msize = u16(block, cursor + 2)
                mflags = u8(block, cursor + 4)
                body = cursor + 8
                if body + msize > length:
                    raise H5Error(f"message overruns object header block at {start + cursor}")
                payload = block[body : body + msize]
                found.append((mtype, mflags, payload))
                if mtype == MSG_CONTINUATION:
                    blocks.append((u64(payload, 0), u64(payload, 8)))
                cursor = body + msize
            if cursor != length:
                raise H5Error(f"object header block at {start} has {length - cursor} stray bytes")
        # The declared count may exceed the parsed messages when the writer
        # merged null messages; it must never be smaller.
        if declared < len(found):
            raise H5Error(f"object header at {address}: declared {declared} < parsed {len(found)}")
        return found

    @staticmethod
    def only(messages, mtype: int) -> tuple[int, bytes]:
        hits = [(f, p) for t, f, p in messages if t == mtype]
        if len(hits) != 1:
            raise H5Error(f"expected exactly one message of type {mtype:#06x}, found {len(hits)}")
        return hits[0]

    # -------------------------------------------------------------- groups
    def group_links(self, header: int) -> dict[str, int]:
        messages = self.messages(header)
        if any(t in (MSG_LINK, MSG_LINK_INFO) for t, _, _ in messages):
            raise H5Error("new-style link-message groups are out of scope")
        _, payload = self.only(messages, MSG_SYMBOL_TABLE)
        btree, heap = u64(payload, 0), u64(payload, 8)
        hdr = self.v.read(heap, 32)
        if hdr[:4] != b"HEAP" or hdr[4] != 0:
            raise H5Error(f"bad local heap at {heap}")
        heap_size, heap_data = u64(hdr, 8), u64(hdr, 24)
        links: dict[str, int] = {}
        self._walk_group_btree(btree, heap_data, heap_size, links, set(), None)
        return links

    def _walk_group_btree(self, node, heap_data, heap_size, links, visited, level_expected):
        if node in visited:
            raise H5Error(f"cyclic group B-tree at {node}")
        visited.add(node)
        hdr = self.v.read(node, 24)
        if hdr[:4] != b"TREE" or hdr[4] != 0:
            raise H5Error(f"bad group B-tree node at {node}")
        level = hdr[5]
        if level_expected is not None and level != level_expected:
            raise H5Error(f"group B-tree level mismatch at {node}")
        entries = u16(hdr, 6)
        body = self.v.read(node + 24, entries * 16 + 8)
        for i in range(entries):
            child = u64(body, i * 16 + 8)
            if level:
                self._walk_group_btree(child, heap_data, heap_size, links, visited, level - 1)
                continue
            snod = self.v.read(child, 8)
            if snod[:4] != b"SNOD" or snod[4] != 1:
                raise H5Error(f"bad symbol-table node at {child}")
            count = u16(snod, 6)
            table = self.v.read(child + 8, count * 40)
            for s in range(count):
                e = s * 40
                name_off = u64(table, e)
                if name_off >= heap_size:
                    raise H5Error("link name offset beyond local heap")
                name = self.v.cstring(heap_data + name_off, heap_size - name_off)
                if name in links:
                    raise H5Error(f"duplicate link {name!r}")
                if u32(table, e + 16) == 2:
                    raise H5Error(f"soft link {name!r} is out of scope")
                links[name] = u64(table, e + 8)

    def resolve(self, path: str) -> int:
        address = self.root_header
        for part in [p for p in path.split("/") if p]:
            links = self.group_links(address)
            if part not in links:
                raise H5Error(f"missing link {part!r} in {path!r}; have {sorted(links)}")
            address = links[part]
        return address

    def is_group(self, header: int) -> bool:
        return any(t == MSG_SYMBOL_TABLE for t, _, _ in self.messages(header))

    def tree(self, header: int | None = None, prefix: str = "") -> dict[str, int]:
        """Return {path: header_address} for every object below a group."""
        header = self.root_header if header is None else header
        out: dict[str, int] = {}
        for name, child in sorted(self.group_links(header).items()):
            path = f"{prefix}/{name}"
            out[path] = child
            if self.is_group(child):
                out.update(self.tree(child, path))
        return out

    # ----------------------------------------------------------- dataspace
    @staticmethod
    def dataspace(payload: bytes) -> tuple[int, ...]:
        version, rank, flags = u8(payload, 0), u8(payload, 1), u8(payload, 2)
        if version == 1:
            cursor = 8
        elif version == 2:
            kind = u8(payload, 3)
            if kind == 0:
                return ()
            if kind != 1:
                raise H5Error(f"unsupported dataspace type {kind}")
            cursor = 4
        else:
            raise H5Error(f"unsupported dataspace version {version}")
        dims = tuple(u64(payload, cursor + 8 * i) for i in range(rank))
        if flags & 1:
            for i, dim in enumerate(dims):
                mx = u64(payload, cursor + 8 * (rank + i))
                if mx != UNDEF and mx < dim:
                    raise H5Error("dataspace maximum below current dimension")
        return dims

    # ---------------------------------------------------------- attributes
    @staticmethod
    def _decode_value(dtype: bytes, dims: tuple[int, ...], data: bytes):
        count = 1
        for d in dims:
            count *= d
        klass, bits0, size = dtype[0] & 0x0F, dtype[1], u32(dtype, 4)
        if klass == 0:
            if bits0 & 1:
                raise H5Error("big-endian integer attribute")
            code = {1: "b", 2: "h", 4: "i", 8: "q"}[size]
            code = code if bits0 & 0x08 else code.upper()
            values = list(struct.unpack_from("<" + code * count, data, 0))
        elif klass == 1:
            if bits0 & 1:
                raise H5Error("big-endian float attribute")
            values = list(struct.unpack_from("<" + {4: "f", 8: "d"}[size] * count, data, 0))
        elif klass == 3:
            values = [data[i * size : (i + 1) * size].split(b"\0", 1)[0].decode("utf-8")
                      for i in range(count)]
        else:
            return f"<datatype class {klass}>"
        return values[0] if not dims else values

    def attributes(self, messages) -> dict[str, object]:
        result: dict[str, object] = {}
        for t, _, p in messages:
            if t != MSG_ATTRIBUTE:
                continue
            version = u8(p, 0)
            name_size, dtype_size, space_size = u16(p, 2), u16(p, 4), u16(p, 6)
            if version == 1:
                c = 8
                name = p[c : c + name_size]; c += pad8(name_size)
                dtype = p[c : c + dtype_size]; c += pad8(dtype_size)
                space = p[c : c + space_size]; c += pad8(space_size)
            elif version in (2, 3):
                if u8(p, 1) & 0x03:
                    continue
                c = 8 if version == 2 else 9
                name = p[c : c + name_size]; c += name_size
                dtype = p[c : c + dtype_size]; c += dtype_size
                space = p[c : c + space_size]; c += space_size
            else:
                raise H5Error(f"unsupported attribute message version {version}")
            key = name.split(b"\0", 1)[0].decode("utf-8")
            try:
                dims = self.dataspace(space)
            except H5Error:
                result[key] = None
                continue
            result[key] = self._decode_value(dtype, dims, p[c:])
        return result

    # ------------------------------------------------------------ datasets
    @staticmethod
    def filters(payload: bytes) -> list[int]:
        version, count = u8(payload, 0), u8(payload, 1)
        cursor = 8 if version == 1 else 2 if version == 2 else None
        if cursor is None:
            raise H5Error(f"unsupported filter pipeline version {version}")
        ids = []
        for _ in range(count):
            fid = u16(payload, cursor); cursor += 2
            name_len = 0
            if version == 1 or fid >= 256:
                name_len = u16(payload, cursor); cursor += 2
            nvalues = u16(payload, cursor + 2); cursor += 4
            cursor += pad8(name_len) if version == 1 else name_len
            cursor += 4 * nvalues
            if version == 1 and nvalues % 2:
                cursor += 4
            ids.append(fid)
        return ids

    def dataset(self, header: int) -> dict[str, object]:
        messages = self.messages(header)
        sf, space = self.only(messages, MSG_DATASPACE)
        tf, dtype = self.only(messages, MSG_DATATYPE)
        lf, layout = self.only(messages, MSG_LAYOUT)
        if (sf | tf | lf) & 0x02:
            raise H5Error("shared dataspace/datatype/layout messages are out of scope")
        if any(t == MSG_EXTERNAL for t, _, _ in messages):
            raise H5Error("external-file storage is out of scope")
        filter_msgs = [p for t, _, p in messages if t == MSG_FILTER]
        if len(filter_msgs) > 1:
            raise H5Error("multiple filter pipeline messages")
        info: dict[str, object] = {
            "shape": self.dataspace(space),
            "datatype": bytes(dtype),
            "filters": self.filters(filter_msgs[0]) if filter_msgs else [],
            "attributes": self.attributes(messages),
        }
        if u8(layout, 0) != 3:
            raise H5Error(f"unsupported layout message version {u8(layout, 0)}")
        cls = u8(layout, 1)
        info["layout_class"] = cls
        if cls == 1:
            info["address"] = u64(layout, 2)
            info["size"] = u64(layout, 10)
        elif cls == 0:
            n = u16(layout, 2)
            info["compact"] = bytes(layout[4 : 4 + n])
        elif cls == 2:
            info["chunked"] = True
        else:
            raise H5Error(f"unknown layout class {cls}")
        return info

    def read_values(self, info: dict[str, object]) -> list:
        """Decode a small contiguous or compact F32LE/F64LE/int dataset."""
        dtype = bytes(info["datatype"])
        if info["filters"]:
            raise H5Error("filtered small dataset is out of scope")
        if info["layout_class"] == 1:
            if info["address"] == UNDEF:
                raise H5Error("contiguous dataset has no storage allocated")
            data = self.v.read(int(info["address"]), int(info["size"]))
        elif info["layout_class"] == 0:
            data = bytes(info["compact"])
        else:
            raise H5Error("chunked small dataset is out of scope")
        value = self._decode_value(dtype, tuple(info["shape"]), data)
        return value if isinstance(value, list) else [value]


def is_f32le(dtype: bytes) -> bool:
    return dtype[: len(H5T_IEEE_F32LE)] == H5T_IEEE_F32LE and not any(dtype[len(H5T_IEEE_F32LE) :])
