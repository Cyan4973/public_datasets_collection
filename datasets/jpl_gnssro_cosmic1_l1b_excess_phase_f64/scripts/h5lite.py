#!/usr/bin/env python3
"""Small pure-standard-library HDF5 reader for NetCDF4 files.

Derived from ``datasets/noaa_cdr_seaice_conc_nh_daily_u8/scripts/h5lite.py``
(same structures, same checksum discipline) with one addition for this
recipe: version-3 Data Layout messages of class 1 (contiguous storage) are
decoded to their raw-data address and size.

Scope is deliberately narrow:

* superblock version 0 or 2/3 (8-byte offsets and lengths)
* version-2 object headers (``OHDR``) with ``OCHK`` continuation chunks
* dense link and attribute storage: Link Info / Attribute Info messages that
  point at a fractal heap (``FRHP``, root direct block or a root indirect
  block of direct blocks) indexed by version-2 B-trees (``BTHD``/``BTIN``/
  ``BTLF``), plus compact Link and Attribute messages
* Dataspace, Datatype, Filter Pipeline and version-3 Data Layout messages
  (contiguous and chunked classes)
* raw-data chunk indexes in version-1 B-trees (``TREE`` node type 1)
* variable-length string attributes held in a global heap (``GCOL``)

Every checksummed metadata block (superblock v2, OHDR/OCHK chunks, fractal
heap header, indirect and direct blocks, v2 B-tree header and nodes) is
verified with the Jenkins lookup3 hash that HDF5 uses.  Anything outside this
scope raises ``H5Error`` instead of guessing.
"""
from __future__ import annotations

import struct

UNDEF = 0xFFFFFFFFFFFFFFFF
_M32 = 0xFFFFFFFF
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"

MSG_DATASPACE = 0x01
MSG_LINK_INFO = 0x02
MSG_DATATYPE = 0x03
MSG_FILL_VALUE = 0x05
MSG_LINK = 0x06
MSG_LAYOUT = 0x08
MSG_FILTERS = 0x0B
MSG_ATTRIBUTE = 0x0C
MSG_CONTINUATION = 0x10
MSG_ATTRIBUTE_INFO = 0x15

BTREE2_LINK_NAME = 5
BTREE2_LINK_ORDER = 6
BTREE2_ATTR_NAME = 8


class H5Error(ValueError):
    """Raised for malformed or out-of-scope HDF5 structures."""


def _rot(x: int, k: int) -> int:
    return ((x << k) | (x >> (32 - k))) & _M32


def lookup3(data: bytes, initval: int = 0) -> int:
    """Bob Jenkins' lookup3 ``hashlittle`` (HDF5 ``H5_checksum_lookup3``)."""
    length = len(data)
    a = b = c = (0xDEADBEEF + length + initval) & _M32
    if length == 0:
        return c
    pos = 0
    while length - pos > 12:
        x, y, z = struct.unpack_from("<3I", data, pos)
        a = (a + x) & _M32
        b = (b + y) & _M32
        c = (c + z) & _M32
        a = (a - c) & _M32; a ^= _rot(c, 4); c = (c + b) & _M32
        b = (b - a) & _M32; b ^= _rot(a, 6); a = (a + c) & _M32
        c = (c - b) & _M32; c ^= _rot(b, 8); b = (b + a) & _M32
        a = (a - c) & _M32; a ^= _rot(c, 16); c = (c + b) & _M32
        b = (b - a) & _M32; b ^= _rot(a, 19); a = (a + c) & _M32
        c = (c - b) & _M32; c ^= _rot(b, 4); b = (b + a) & _M32
        pos += 12
    tail = bytes(data[pos:]) + b"\x00" * (12 - (length - pos))
    x, y, z = struct.unpack("<3I", tail)
    a = (a + x) & _M32
    b = (b + y) & _M32
    c = (c + z) & _M32
    c ^= b; c = (c - _rot(b, 14)) & _M32
    a ^= c; a = (a - _rot(c, 11)) & _M32
    b ^= a; b = (b - _rot(a, 25)) & _M32
    c ^= b; c = (c - _rot(b, 16)) & _M32
    a ^= c; a = (a - _rot(c, 4)) & _M32
    b ^= a; b = (b - _rot(a, 14)) & _M32
    c ^= b; c = (c - _rot(b, 24)) & _M32
    return c


def limit_enc_size(value: int) -> int:
    """``H5VM_limit_enc_size``: bytes needed to encode ``value``."""
    return (max(value, 1).bit_length() - 1) // 8 + 1


def _uint(buf: bytes, pos: int, size: int) -> int:
    if pos + size > len(buf):
        raise H5Error("integer field exceeds buffer")
    return int.from_bytes(buf[pos:pos + size], "little")


class H5File:
    """Read-only view over one complete in-memory HDF5 file."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.checked_blocks = 0
        if raw[:8] != HDF5_SIGNATURE:
            raise H5Error("missing HDF5 signature")
        self.superblock_version = raw[8]
        if raw[8] == 0:
            fs_ver, root_ver, _r1, sh_ver, so, sl, _r2 = struct.unpack_from("<7B", raw, 9)
            if (fs_ver, root_ver, sh_ver, so, sl) != (0, 0, 0, 8, 8):
                raise H5Error("unexpected superblock v0 field values")
            base, _free, eof, _driver = struct.unpack_from("<4Q", raw, 24)
            _name_offset, self.root_addr = struct.unpack_from("<QQ", raw, 56)
        elif raw[8] in (2, 3):
            if (raw[9], raw[10]) != (8, 8):
                raise H5Error("unexpected superblock offset/length sizes")
            base, extension, eof, self.root_addr = struct.unpack_from("<4Q", raw, 12)
            if extension != UNDEF:
                raise H5Error("superblock extension present (out of scope)")
            self._checksum(0, 44, "superblock")
        else:
            raise H5Error(f"unsupported superblock version {raw[8]}")
        if base != 0:
            raise H5Error("nonzero HDF5 base address")
        if eof != len(raw):
            raise H5Error(f"superblock end-of-file {eof} != file size {len(raw)}")

    # ------------------------------------------------------------------ utils
    def _checksum(self, start: int, end: int, what: str) -> None:
        if end + 4 > len(self.raw) or start < 0 or end < start:
            raise H5Error(f"{what} extent exceeds file")
        stored = struct.unpack_from("<I", self.raw, end)[0]
        actual = lookup3(self.raw[start:end])
        if stored != actual:
            raise H5Error(
                f"{what} checksum mismatch at {start}: stored={stored:08x} actual={actual:08x}"
            )
        self.checked_blocks += 1

    def _signature(self, addr: int, signature: bytes) -> None:
        if addr == UNDEF or addr < 0 or addr + 4 > len(self.raw):
            raise H5Error(f"invalid address {addr} for {signature!r}")
        if self.raw[addr:addr + 4] != signature:
            raise H5Error(f"expected {signature!r} at {addr}")

    # --------------------------------------------------------- object headers
    def messages(self, addr: int) -> list[tuple[int, int, bytes]]:
        """(type, flags, payload) of every non-null message in a v2 header."""
        raw = self.raw
        self._signature(addr, b"OHDR")
        if raw[addr + 4] != 2:
            raise H5Error(f"unsupported object header version {raw[addr + 4]} at {addr}")
        flags = raw[addr + 5]
        if flags & 0xC0:
            raise H5Error("reserved object header flag bits set")
        pos = addr + 6
        if flags & 0x20:
            pos += 16
        if flags & 0x10:
            pos += 4
        size_len = 1 << (flags & 0x03)
        chunk_size = _uint(raw, pos, size_len)
        pos += size_len
        header_len = 6 if flags & 0x04 else 4
        pending = [(pos, pos + chunk_size, addr)]
        seen: set[int] = {addr}
        out: list[tuple[int, int, bytes]] = []
        while pending:
            start, end, block_start = pending.pop(0)
            self._checksum(block_start, end, "object header chunk")
            cursor = start
            while cursor + header_len <= end:
                mtype = raw[cursor]
                msize = struct.unpack_from("<H", raw, cursor + 1)[0]
                mflags = raw[cursor + 3]
                payload_start = cursor + header_len
                payload_end = payload_start + msize
                if payload_end > end:
                    raise H5Error("object header message exceeds its chunk")
                payload = raw[payload_start:payload_end]
                if mtype == MSG_CONTINUATION:
                    caddr, clen = struct.unpack_from("<QQ", payload, 0)
                    if caddr in seen:
                        raise H5Error("object header continuation loop")
                    seen.add(caddr)
                    self._signature(caddr, b"OCHK")
                    if clen < 8:
                        raise H5Error("continuation chunk too short")
                    pending.append((caddr + 4, caddr + clen - 4, caddr))
                elif mtype != 0:
                    out.append((mtype, mflags, payload))
                cursor = payload_end
        return out

    @staticmethod
    def single(messages: list[tuple[int, int, bytes]], mtype: int) -> bytes:
        found = [(flags, payload) for kind, flags, payload in messages if kind == mtype]
        if len(found) != 1:
            raise H5Error(f"expected one message of type {mtype:#x}, found {len(found)}")
        flags, payload = found[0]
        if flags & 0x02:
            raise H5Error(f"shared message of type {mtype:#x} is out of scope")
        return payload

    # ----------------------------------------------------------- fractal heap
    def fractal_heap(self, addr: int) -> dict:
        raw = self.raw
        self._signature(addr, b"FRHP")
        if raw[addr + 4] != 0:
            raise H5Error("unsupported fractal heap version")
        pos = addr + 5
        id_len, filter_len = struct.unpack_from("<HH", raw, pos)
        pos += 4
        heap_flags = raw[pos]
        pos += 1
        max_managed = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        fields = struct.unpack_from("<12Q", raw, pos)
        pos += 96
        n_managed, huge_size, n_huge = fields[7], fields[8], fields[9]
        width = struct.unpack_from("<H", raw, pos)[0]
        pos += 2
        start_block, max_direct = struct.unpack_from("<QQ", raw, pos)
        pos += 16
        max_heap_bits, _start_rows = struct.unpack_from("<HH", raw, pos)
        pos += 4
        root = struct.unpack_from("<Q", raw, pos)[0]
        pos += 8
        current_rows = struct.unpack_from("<H", raw, pos)[0]
        pos += 2
        if filter_len:
            raise H5Error("filtered fractal heaps are out of scope")
        self._checksum(addr, pos, "fractal heap header")
        if n_huge or huge_size:
            raise H5Error("fractal heap holds huge objects (out of scope)")
        for value, label in ((width, "width"), (start_block, "start block"), (max_direct, "max direct block")):
            if value <= 0 or value & (value - 1):
                raise H5Error(f"fractal heap {label} is not a power of two")
        heap = {
            "addr": addr,
            "id_len": id_len,
            "flags": heap_flags,
            "width": width,
            "start_block": start_block,
            "off_size": (max_heap_bits + 7) // 8,
            # H5HF: MIN(H5HF_SIZEOF_OFFSET_LEN(max_direct), limit_enc_size(max_managed))
            "len_size": min(((max_direct.bit_length() - 1) + 7) // 8, limit_enc_size(max_managed)),
            "max_direct_rows": (max_direct.bit_length() - 1) - (start_block.bit_length() - 1) + 2,
            "n_managed": n_managed,
            "blocks": [],
        }
        if root != UNDEF:
            if current_rows == 0:
                heap["blocks"].append(self._direct_block(heap, root, 0, start_block))
            else:
                self._root_indirect_block(heap, root, current_rows)
        return heap

    @staticmethod
    def _row_block_size(heap: dict, row: int) -> int:
        return heap["start_block"] if row == 0 else heap["start_block"] << (row - 1)

    def _direct_block(self, heap: dict, addr: int, expected_offset: int, size: int) -> tuple[int, int, int]:
        raw = self.raw
        self._signature(addr, b"FHDB")
        if raw[addr + 4] != 0:
            raise H5Error("unsupported fractal heap direct block version")
        if struct.unpack_from("<Q", raw, addr + 5)[0] != heap["addr"]:
            raise H5Error("direct block belongs to a different heap")
        block_offset = _uint(raw, addr + 13, heap["off_size"])
        if block_offset != expected_offset:
            raise H5Error(f"direct block offset {block_offset} != expected {expected_offset}")
        if addr + size > len(raw):
            raise H5Error("direct block exceeds file")
        if heap["flags"] & 0x02:
            checksum_pos = 13 + heap["off_size"]
            block = bytearray(raw[addr:addr + size])
            stored = struct.unpack_from("<I", block, checksum_pos)[0]
            block[checksum_pos:checksum_pos + 4] = b"\x00\x00\x00\x00"
            if lookup3(bytes(block)) != stored:
                raise H5Error(f"direct block checksum mismatch at {addr}")
            self.checked_blocks += 1
        return (block_offset, size, addr)

    def _root_indirect_block(self, heap: dict, addr: int, rows: int) -> None:
        raw = self.raw
        self._signature(addr, b"FHIB")
        if raw[addr + 4] != 0:
            raise H5Error("unsupported fractal heap indirect block version")
        if struct.unpack_from("<Q", raw, addr + 5)[0] != heap["addr"]:
            raise H5Error("indirect block belongs to a different heap")
        if _uint(raw, addr + 13, heap["off_size"]) != 0:
            raise H5Error("root indirect block offset is not zero")
        if rows > heap["max_direct_rows"]:
            raise H5Error("nested fractal heap indirect blocks are out of scope")
        pos = addr + 13 + heap["off_size"]
        children = []
        offset = 0
        for row in range(rows):
            size = self._row_block_size(heap, row)
            for _column in range(heap["width"]):
                children.append((struct.unpack_from("<Q", raw, pos)[0], offset, size))
                pos += 8
                offset += size
        self._checksum(addr, pos, "fractal heap indirect block")
        for child, child_offset, size in children:
            if child != UNDEF:
                heap["blocks"].append(self._direct_block(heap, child, child_offset, size))

    def heap_object(self, heap: dict, heap_id: bytes) -> bytes:
        if len(heap_id) != heap["id_len"]:
            raise H5Error("heap ID length mismatch")
        first = heap_id[0]
        if first >> 6:
            raise H5Error("unsupported heap ID version")
        kind = (first >> 4) & 0x03
        if kind == 2:
            if heap["id_len"] > 18:
                raise H5Error("extended tiny heap IDs are out of scope")
            length = (first & 0x0F) + 1
            return bytes(heap_id[1:1 + length])
        if kind != 0:
            raise H5Error(f"heap object kind {kind} is out of scope")
        offset = _uint(heap_id, 1, heap["off_size"])
        length = _uint(heap_id, 1 + heap["off_size"], heap["len_size"])
        for block_offset, size, block_addr in heap["blocks"]:
            if block_offset <= offset < block_offset + size:
                if offset + length > block_offset + size:
                    raise H5Error("heap object crosses its direct block")
                start = block_addr + offset - block_offset
                return self.raw[start:start + length]
        raise H5Error(f"heap offset {offset} is not inside any direct block")

    # -------------------------------------------------------------- v2 B-tree
    def btree2_records(self, addr: int, expected_type: int, expected_record_size: int) -> list[bytes]:
        raw = self.raw
        self._signature(addr, b"BTHD")
        if raw[addr + 4] != 0 or raw[addr + 5] != expected_type:
            raise H5Error(f"v2 B-tree version/type mismatch (want type {expected_type})")
        node_size = struct.unpack_from("<I", raw, addr + 6)[0]
        record_size, depth = struct.unpack_from("<HH", raw, addr + 10)
        root = struct.unpack_from("<Q", raw, addr + 16)[0]
        root_records = struct.unpack_from("<H", raw, addr + 24)[0]
        total = struct.unpack_from("<Q", raw, addr + 26)[0]
        self._checksum(addr, addr + 34, "v2 B-tree header")
        if record_size != expected_record_size:
            raise H5Error(f"v2 B-tree record size {record_size} != {expected_record_size}")
        if root == UNDEF:
            if total:
                raise H5Error("empty v2 B-tree claims records")
            return []
        # Node geometry as computed by H5B2__hdr_init.
        leaf_max = (node_size - 10) // record_size
        max_nrec_size = limit_enc_size(leaf_max)
        cumulative = [leaf_max]
        cumulative_size = [0]
        for level in range(1, depth + 1):
            pointer = 8 + max_nrec_size + (cumulative_size[level - 1] if level > 1 else 0)
            level_max = (node_size - (10 + pointer)) // (record_size + pointer)
            cumulative.append((level_max + 1) * cumulative[level - 1] + level_max)
            cumulative_size.append(limit_enc_size(cumulative[level]))
        records: list[bytes] = []

        def visit(node: int, count: int, level: int) -> None:
            self._signature(node, b"BTLF" if level == 0 else b"BTIN")
            if raw[node + 4] != 0 or raw[node + 5] != expected_type:
                raise H5Error("v2 B-tree node version/type mismatch")
            pos = node + 6
            for _ in range(count):
                records.append(raw[pos:pos + record_size])
                pos += record_size
            children = []
            if level:
                for _ in range(count + 1):
                    child = struct.unpack_from("<Q", raw, pos)[0]
                    pos += 8
                    child_count = _uint(raw, pos, max_nrec_size)
                    pos += max_nrec_size
                    if level > 1:
                        pos += cumulative_size[level - 1]
                    children.append((child, child_count))
            self._checksum(node, pos, "v2 B-tree node")
            for child, child_count in children:
                visit(child, child_count, level - 1)

        visit(root, root_records, depth)
        if len(records) != total:
            raise H5Error(f"v2 B-tree holds {len(records)} records, header says {total}")
        return records

    # ------------------------------------------------------------------ links
    def links(self, addr: int, index: str = "name") -> dict[str, int]:
        """Hard links of a group, resolved via the name or creation-order index."""
        messages = self.messages(addr)
        payloads = [payload for kind, _flags, payload in messages if kind == MSG_LINK]
        infos = [payload for kind, _flags, payload in messages if kind == MSG_LINK_INFO]
        if len(infos) > 1:
            raise H5Error("multiple Link Info messages")
        if infos:
            info = infos[0]
            if info[0] != 0:
                raise H5Error("unsupported Link Info version")
            link_flags = info[1]
            pos = 2 + (8 if link_flags & 0x01 else 0)
            heap_addr, name_btree = struct.unpack_from("<QQ", info, pos)
            pos += 16
            order_btree = struct.unpack_from("<Q", info, pos)[0] if link_flags & 0x02 else UNDEF
            if heap_addr != UNDEF:
                if payloads:
                    raise H5Error("group mixes compact and dense link storage")
                heap = self.fractal_heap(heap_addr)
                if index == "name":
                    records = self.btree2_records(name_btree, BTREE2_LINK_NAME, 4 + heap["id_len"])
                    ids = [record[4:] for record in records]
                elif index == "creation_order":
                    if order_btree == UNDEF:
                        raise H5Error("group has no creation-order index")
                    records = self.btree2_records(order_btree, BTREE2_LINK_ORDER, 8 + heap["id_len"])
                    ids = [record[8:] for record in records]
                else:
                    raise H5Error(f"unknown link index {index!r}")
                payloads = [self.heap_object(heap, heap_id) for heap_id in ids]
                if len(payloads) != heap["n_managed"]:
                    raise H5Error("link index and fractal heap object counts disagree")
        out: dict[str, int] = {}
        for payload in payloads:
            name, target = decode_link(payload)
            if name in out:
                raise H5Error(f"duplicate link name {name!r}")
            out[name] = target
        return out

    # ------------------------------------------------------------- attributes
    def attributes(self, addr: int) -> dict[str, object]:
        messages = self.messages(addr)
        payloads = [payload for kind, _flags, payload in messages if kind == MSG_ATTRIBUTE]
        infos = [payload for kind, _flags, payload in messages if kind == MSG_ATTRIBUTE_INFO]
        if len(infos) > 1:
            raise H5Error("multiple Attribute Info messages")
        if infos:
            info = infos[0]
            if info[0] != 0:
                raise H5Error("unsupported Attribute Info version")
            pos = 2 + (2 if info[1] & 0x01 else 0)
            heap_addr, name_btree = struct.unpack_from("<QQ", info, pos)
            if heap_addr != UNDEF:
                heap = self.fractal_heap(heap_addr)
                if heap["id_len"] != 8:
                    raise H5Error("attribute heap ID length is not 8")
                for record in self.btree2_records(name_btree, BTREE2_ATTR_NAME, 17):
                    if record[8] & 0x02:
                        raise H5Error("shared attribute message is out of scope")
                    payloads.append(self.heap_object(heap, record[:8]))
        out: dict[str, object] = {}
        for payload in payloads:
            name, value = self.decode_attribute(payload)
            if name in out:
                raise H5Error(f"duplicate attribute {name!r}")
            out[name] = value
        return out

    def decode_attribute(self, payload: bytes) -> tuple[str, object]:
        version = payload[0]
        if version not in (1, 2, 3):
            raise H5Error(f"unsupported attribute message version {version}")
        if version > 1 and payload[1] & 0x03:
            raise H5Error("attribute with shared datatype/dataspace is out of scope")
        name_size, type_size, space_size = struct.unpack_from("<HHH", payload, 2)
        pos = 8 + (1 if version == 3 else 0)

        def take(size: int) -> bytes:
            nonlocal pos
            chunk = payload[pos:pos + size]
            pos += ((size + 7) & ~7) if version == 1 else size
            return chunk

        name = take(name_size).split(b"\x00", 1)[0].decode("utf-8")
        datatype = take(type_size)
        dims = decode_dataspace(take(space_size))
        count = 1
        for dim in dims:
            count *= dim
        return name, self.decode_values(datatype, payload[pos:], count)

    def decode_values(self, datatype: bytes, data: bytes, count: int) -> object:
        klass = datatype[0] & 0x0F
        bits = datatype[1] | (datatype[2] << 8) | (datatype[3] << 16)
        size = struct.unpack_from("<I", datatype, 4)[0]
        if klass in (0, 1):
            if bits & 0x01:
                raise H5Error("big-endian numeric attribute is out of scope")
            if klass == 0:
                code = {1: "b", 2: "h", 4: "i", 8: "q"}[size]
                code = code if bits & 0x08 else code.upper()
            else:
                code = {4: "f", 8: "d"}[size]
            return list(struct.unpack_from(f"<{count}{code}", data, 0))
        if klass == 3:
            return data[:size * count].split(b"\x00", 1)[0].decode("utf-8")
        if klass == 9 and bits & 0x0F == 1:
            strings = []
            for item in range(count):
                length, heap_addr, heap_index = struct.unpack_from("<IQI", data, item * 16)
                strings.append(self.global_heap_object(heap_addr, heap_index)[:length].decode("utf-8"))
            return strings[0] if count == 1 else strings
        return {"undecoded_datatype_class": klass, "count": count}

    def global_heap_object(self, addr: int, index: int) -> bytes:
        raw = self.raw
        self._signature(addr, b"GCOL")
        if raw[addr + 4] != 1:
            raise H5Error("unsupported global heap version")
        collection_size = struct.unpack_from("<Q", raw, addr + 8)[0]
        pos = addr + 16
        end = addr + collection_size
        if end > len(raw):
            raise H5Error("global heap collection exceeds file")
        while pos + 16 <= end:
            object_index = struct.unpack_from("<H", raw, pos)[0]
            object_size = struct.unpack_from("<Q", raw, pos + 8)[0]
            if object_index == 0:
                break
            if object_index == index:
                return raw[pos + 16:pos + 16 + object_size]
            pos += 16 + ((object_size + 7) & ~7)
        raise H5Error(f"global heap object {index} not found")

    # --------------------------------------------------------------- datasets
    def dataset(self, addr: int) -> dict:
        messages = self.messages(addr)
        layout = self.single(messages, MSG_LAYOUT)
        info = {
            "shape": decode_dataspace(self.single(messages, MSG_DATASPACE)),
            "datatype": self.single(messages, MSG_DATATYPE),
            "layout_raw": layout,
            "filters": [],
        }
        filters = [(flags, payload) for kind, flags, payload in messages if kind == MSG_FILTERS]
        if len(filters) > 1:
            raise H5Error("multiple filter pipeline messages")
        if filters:
            info["filters"] = decode_filters(self.single(messages, MSG_FILTERS))
        if layout[0] != 3:
            raise H5Error(f"data layout version {layout[0]} is out of scope")
        info["layout_class"] = layout[1]
        if layout[1] == 1:
            if len(layout) != 18:
                raise H5Error("unexpected contiguous layout message length")
            info["data_addr"], info["data_size"] = struct.unpack_from("<QQ", layout, 2)
        elif layout[1] == 2:
            rank = layout[2]
            info["chunk_btree"] = struct.unpack_from("<Q", layout, 3)[0]
            info["chunk_dims"] = struct.unpack_from(f"<{rank}I", layout, 11)
            if len(layout) != 11 + 4 * rank:
                raise H5Error("unexpected chunked layout message length")
        return info

    def chunk_index(self, addr: int, rank: int) -> tuple[list[tuple[int, int, tuple[int, ...], int]], tuple[int, ...]]:
        """Leaf entries (stored size, filter mask, offsets, address) and the final key offsets."""
        raw = self.raw
        out: list[tuple[int, int, tuple[int, ...], int]] = []
        final_key: list[tuple[int, ...]] = []
        key_size = 8 + 8 * rank

        def visit(node: int, expected_level: int | None) -> None:
            self._signature(node, b"TREE")
            if raw[node + 4] != 1:
                raise H5Error("v1 B-tree is not a raw-data chunk index")
            level = raw[node + 5]
            if expected_level is not None and level != expected_level:
                raise H5Error("v1 B-tree level mismatch")
            used = struct.unpack_from("<H", raw, node + 6)[0]
            pos = node + 24
            for _ in range(used):
                size, mask = struct.unpack_from("<II", raw, pos)
                offsets = struct.unpack_from(f"<{rank}Q", raw, pos + 8)
                child = struct.unpack_from("<Q", raw, pos + key_size)[0]
                pos += key_size + 8
                if level == 0:
                    out.append((size, mask, offsets, child))
                else:
                    visit(child, level - 1)
            final_key.append(struct.unpack_from(f"<{rank}Q", raw, pos + 8))

        visit(addr, None)
        return out, final_key[-1]


def decode_link(payload: bytes) -> tuple[str, int]:
    if payload[0] != 1:
        raise H5Error("unsupported link message version")
    flags = payload[1]
    pos = 2
    link_type = 0
    if flags & 0x08:
        link_type = payload[pos]
        pos += 1
    if flags & 0x04:
        pos += 8
    if flags & 0x10:
        pos += 1
    length_size = 1 << (flags & 0x03)
    name_length = _uint(payload, pos, length_size)
    pos += length_size
    name = payload[pos:pos + name_length].decode("utf-8")
    pos += name_length
    if link_type != 0:
        raise H5Error(f"link {name!r} is not a hard link")
    if pos + 8 != len(payload):
        raise H5Error(f"unexpected link message length for {name!r}")
    return name, struct.unpack_from("<Q", payload, pos)[0]


def decode_dataspace(payload: bytes) -> tuple[int, ...]:
    version, rank = payload[0], payload[1]
    if version == 1:
        pos = 8
    elif version == 2:
        if payload[3] == 0:
            return ()
        if payload[3] == 2:
            return (0,)
        pos = 4
    else:
        raise H5Error(f"unsupported dataspace version {version}")
    return tuple(struct.unpack_from(f"<{rank}Q", payload, pos))


def decode_filters(payload: bytes) -> list[tuple[int, int, tuple[int, ...]]]:
    """(filter id, flags, client data) for each pipeline entry in write order."""
    version, count = payload[0], payload[1]
    out = []
    if version == 1:
        pos = 8
        for _ in range(count):
            filter_id, name_length, flags, n_values = struct.unpack_from("<4H", payload, pos)
            pos += 8 + ((name_length + 7) & ~7)
            values = struct.unpack_from(f"<{n_values}I", payload, pos)
            pos += 4 * n_values + (4 if n_values % 2 else 0)
            out.append((filter_id, flags, values))
    elif version == 2:
        pos = 2
        for _ in range(count):
            filter_id = struct.unpack_from("<H", payload, pos)[0]
            pos += 2
            name_length = 0
            if filter_id >= 256:
                name_length = struct.unpack_from("<H", payload, pos)[0]
                pos += 2
            flags, n_values = struct.unpack_from("<HH", payload, pos)
            pos += 4 + name_length
            values = struct.unpack_from(f"<{n_values}I", payload, pos)
            pos += 4 * n_values
            out.append((filter_id, flags, values))
    else:
        raise H5Error(f"unsupported filter pipeline version {version}")
    if pos > len(payload):
        raise H5Error("filter pipeline message is truncated")
    return out
