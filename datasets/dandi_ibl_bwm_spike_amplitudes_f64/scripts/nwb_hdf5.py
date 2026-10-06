#!/usr/bin/env python3
"""Minimal, strict, standard-library HDF5 reader for the IBL Brain-Wide Map NWB files.

Adapted from the accepted DANDI:001076 recipe's reader. Scope is deliberately
narrow: superblock version 0 with 8-byte offsets and lengths, version-1 object
headers (with continuation blocks), symbol-table groups (v1 group B-trees,
SNOD nodes, local heaps), simple dataspaces, scalar or small attributes
(numeric, fixed-length string, variable-length string via the global heap),
contiguous scalar string datasets, and chunked datasets indexed by a v1
raw-data chunk B-tree. Anything outside this scope raises ``ValueError``.

``raw`` may be any object supporting ``len(raw)`` and ``raw[a:b] -> bytes``.
``BlockStore`` provides that interface over a sparse set of locally cached,
64 KiB-aligned byte ranges of the remote file; reading a block that has not
been fetched raises ``MissingBlock`` so that download.sh can fetch it with curl
and retry (the parser itself never touches the network).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
UNDEFINED_ADDRESS = 0xFFFFFFFFFFFFFFFF
BLOCK_SIZE = 65536

MSG_NIL = 0x00
MSG_DATASPACE = 0x01
MSG_LINK_INFO = 0x02
MSG_DATATYPE = 0x03
MSG_FILL_OLD = 0x04
MSG_FILL = 0x05
MSG_LINK = 0x06
MSG_LAYOUT = 0x08
MSG_GROUP_INFO = 0x0A
MSG_FILTER = 0x0B
MSG_ATTRIBUTE = 0x0C
MSG_CONTINUATION = 0x10
MSG_SYMBOL_TABLE = 0x11

FILTER_DEFLATE = 1

# H5T_IEEE_F64LE datatype message: class 1 (float) version 1, little-endian,
# IEEE normalization, sign bit 63, size 8, offset 0, precision 64, exponent at
# bit 52 size 11, mantissa at bit 0 size 52, bias 1023.
H5T_IEEE_F64LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
# H5T_STD_U32LE datatype message: class 0 (fixed-point) version 1,
# little-endian, unsigned, size 4, bit offset 0, precision 32.
H5T_STD_U32LE = bytes.fromhex("10000000040000000000200000000000")


class MissingBlock(Exception):
    """A metadata block of the remote file has not been fetched yet."""

    def __init__(self, index: int) -> None:
        super().__init__(f"missing block {index}")
        self.index = index


class BlockStore:
    """Read-only view of a remote file backed by locally cached aligned blocks.

    Block ``i`` covers bytes ``[i * BLOCK_SIZE, min(size, (i + 1) * BLOCK_SIZE))``
    and lives at ``<directory>/blk_<i:06d>.bin``.
    """

    def __init__(self, directory: Path, size: int, block_size: int = BLOCK_SIZE) -> None:
        self.directory = Path(directory)
        self.size = int(size)
        self.block_size = int(block_size)
        self.cache: dict[int, bytes] = {}
        self.used: set[int] = set()

    def __len__(self) -> int:
        return self.size

    def block_count(self) -> int:
        return (self.size + self.block_size - 1) // self.block_size

    def block_span(self, index: int) -> tuple[int, int]:
        start = index * self.block_size
        if index < 0 or start >= self.size:
            raise ValueError(f"block {index} outside file of {self.size} bytes")
        return start, min(self.size, start + self.block_size)

    def block_path(self, index: int) -> Path:
        return self.directory / f"blk_{index:06d}.bin"

    def block(self, index: int) -> bytes:
        if index in self.cache:
            self.used.add(index)
            return self.cache[index]
        path = self.block_path(index)
        if not path.is_file():
            raise MissingBlock(index)
        data = path.read_bytes()
        start, end = self.block_span(index)
        if len(data) != end - start:
            raise ValueError(f"cached block {path} has {len(data)} bytes, expected {end - start}")
        self.cache[index] = data
        self.used.add(index)
        return data

    def __getitem__(self, item: slice) -> bytes:
        if not isinstance(item, slice) or item.step not in (None, 1):
            raise TypeError("BlockStore supports contiguous slices only")
        start = 0 if item.start is None else int(item.start)
        stop = self.size if item.stop is None else min(int(item.stop), self.size)
        if start < 0 or start > stop:
            raise ValueError(f"bad slice {start}:{stop}")
        out = bytearray()
        position = start
        while position < stop:
            index = position // self.block_size
            data = self.block(index)
            offset = position - index * self.block_size
            take = min(stop - position, len(data) - offset)
            out += data[offset : offset + take]
            position += take
        return bytes(out)


def u8(raw, offset: int) -> int:
    return raw[offset : offset + 1][0]


def u16(raw, offset: int) -> int:
    return struct.unpack("<H", raw[offset : offset + 2])[0]


def u32(raw, offset: int) -> int:
    return struct.unpack("<I", raw[offset : offset + 4])[0]


def u64(raw, offset: int) -> int:
    return struct.unpack("<Q", raw[offset : offset + 8])[0]


def pad8(value: int) -> int:
    return (value + 7) & ~7


class H5File:
    def __init__(self, raw, expected_size: int | None = None) -> None:
        self.raw = raw
        self.size = len(raw)
        if expected_size is not None and self.size != expected_size:
            raise ValueError(f"file size {self.size} != expected {expected_size}")
        head = raw[0:96]
        if len(head) < 96 or head[:8] != HDF5_SIGNATURE:
            raise ValueError("missing HDF5 signature")
        if head[8] != 0:
            raise ValueError(f"unsupported superblock version {head[8]}")
        if head[13] != 8 or head[14] != 8:
            raise ValueError("expected 8-byte offsets and lengths")
        if u64(head, 24) != 0:
            raise ValueError("nonzero HDF5 base address")
        eof = u64(head, 40)
        if eof != self.size:
            raise ValueError(f"HDF5 end-of-file address {eof} != file size {self.size}")
        self.root_header = u64(head, 64)
        self.root_btree = u64(head, 80)
        self.root_heap = u64(head, 88)
        self.metadata_reads = 0

    # ------------------------------------------------------------------ io
    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self.size:
            raise ValueError(f"read out of range: offset={offset} length={length} size={self.size}")
        data = self.raw[offset : offset + length]
        if len(data) != length:
            raise ValueError(f"short read at {offset}")
        self.metadata_reads += 1
        return bytes(data)

    # ------------------------------------------------------- object header
    def messages(self, address: int) -> list[tuple[int, int, bytes]]:
        """Return (type, flags, payload) for every message of a v1 object header."""
        prefix = self.read(address, 16)
        if prefix[:4] == b"OHDR":
            raise ValueError(f"version-2 object header at {address} is out of scope")
        if prefix[0] != 1:
            raise ValueError(f"unsupported object header version {prefix[0]} at {address}")
        total = u16(prefix, 2)
        blocks = [(address + 16, u32(prefix, 8))]
        found: list[tuple[int, int, bytes]] = []
        seen_blocks: set[int] = set()
        while blocks:
            start, length = blocks.pop(0)
            if start in seen_blocks:
                raise ValueError(f"cyclic object-header continuation at {start}")
            seen_blocks.add(start)
            block = self.read(start, length)
            cursor = 0
            while cursor + 8 <= length:
                mtype, msize, mflags = struct.unpack_from("<HHB", block, cursor)
                body_start = cursor + 8
                body_end = body_start + msize
                if body_end > length:
                    raise ValueError(f"object-header message overruns block at {start + cursor}")
                payload = block[body_start:body_end]
                found.append((mtype, mflags, payload))
                if mtype == MSG_CONTINUATION:
                    blocks.append((u64(payload, 0), u64(payload, 8)))
                cursor = body_end
        if len(found) != total:
            raise ValueError(f"object header at {address}: expected {total} messages, parsed {len(found)}")
        return found

    @staticmethod
    def only(messages: list[tuple[int, int, bytes]], mtype: int) -> tuple[int, bytes]:
        hits = [(flags, payload) for kind, flags, payload in messages if kind == mtype]
        if len(hits) != 1:
            raise ValueError(f"expected exactly one message of type {mtype:#x}, found {len(hits)}")
        return hits[0]

    # --------------------------------------------------------------- groups
    def _heap_data(self, heap: int) -> tuple[int, int]:
        header = self.read(heap, 32)
        if header[:4] != b"HEAP" or header[4] != 0:
            raise ValueError(f"bad local heap at {heap}")
        return u64(header, 24), u64(header, 8)

    def _heap_name(self, data_address: int, data_size: int, offset: int) -> str:
        if offset >= data_size:
            raise ValueError("link name offset beyond local heap")
        window = self.read(data_address + offset, min(1024, data_size - offset))
        end = window.find(b"\0")
        if end < 0:
            raise ValueError("unterminated link name in local heap")
        return window[:end].decode("utf-8")

    def _group_btree(self, node: int, heap_data: int, heap_size: int, links: dict[str, int | None],
                     visited: set[int], expected_level: int | None) -> None:
        if node in visited:
            raise ValueError(f"cyclic group B-tree at {node}")
        visited.add(node)
        header = self.read(node, 24)
        if header[:4] != b"TREE" or header[4] != 0:
            raise ValueError(f"bad group B-tree node at {node}")
        level = header[5]
        if expected_level is not None and level != expected_level:
            raise ValueError(f"group B-tree level mismatch at {node}")
        entries = u16(header, 6)
        body = self.read(node + 24, entries * 16 + 8)
        for index in range(entries):
            child = u64(body, index * 16 + 8)
            if level:
                self._group_btree(child, heap_data, heap_size, links, visited, level - 1)
                continue
            snod = self.read(child, 8)
            if snod[:4] != b"SNOD" or snod[4] != 1:
                raise ValueError(f"bad symbol-table node at {child}")
            count = u16(snod, 6)
            table = self.read(child + 8, count * 40)
            for symbol in range(count):
                entry = symbol * 40
                name = self._heap_name(heap_data, heap_size, u64(table, entry))
                if name in links:
                    raise ValueError(f"duplicate link name {name!r}")
                cache_type = u32(table, entry + 16)
                if cache_type == 2:
                    links[name] = None  # soft link; never followed by this reader
                else:
                    links[name] = u64(table, entry + 8)

    def group_links(self, header_address: int) -> dict[str, int | None]:
        if header_address == self.root_header:
            btree, heap = self.root_btree, self.root_heap
        else:
            messages = self.messages(header_address)
            if any(kind in (MSG_LINK, MSG_LINK_INFO) for kind, _, _ in messages):
                raise ValueError("new-style (link-message) groups are out of scope")
            _, payload = self.only(messages, MSG_SYMBOL_TABLE)
            btree, heap = u64(payload, 0), u64(payload, 8)
        heap_data, heap_size = self._heap_data(heap)
        links: dict[str, int | None] = {}
        self._group_btree(btree, heap_data, heap_size, links, set(), None)
        return links

    def resolve(self, path: str) -> int:
        address = self.root_header
        for part in [piece for piece in path.split("/") if piece]:
            links = self.group_links(address)
            if part not in links:
                raise ValueError(f"missing HDF5 link {part!r} in path {path!r}; have {sorted(links)}")
            target = links[part]
            if target is None:
                raise ValueError(f"HDF5 link {part!r} in path {path!r} is a soft link")
            address = target
        return address

    def is_group(self, header_address: int) -> bool:
        if header_address == self.root_header:
            return True
        return any(kind == MSG_SYMBOL_TABLE for kind, _, _ in self.messages(header_address))

    def scalar_string(self, header_address: int) -> str:
        """Value of a scalar variable-length or fixed-length string dataset."""
        info = self.dataset(header_address)
        dtype = info["datatype"]
        if info["shape"] != ():
            raise ValueError("string dataset is not scalar")
        if info["layout_class"] == 1:
            data = self.read(int(info["contiguous_address"]), int(info["contiguous_size"]))
        elif info["layout_class"] == 0:
            data = bytes(info["compact_data"])
        else:
            raise ValueError("chunked string dataset is out of scope")
        value = self._decode_attribute_value(dtype, (), data)
        if not isinstance(value, str):
            raise ValueError("dataset is not a string")
        return value

    # ---------------------------------------------------------- dataspace
    @staticmethod
    def dataspace(payload: bytes) -> tuple[int, ...]:
        version, rank, flags = payload[0], payload[1], payload[2]
        if version == 1:
            cursor = 8
        elif version == 2:
            if payload[3] == 2:
                raise ValueError("null dataspace")
            cursor = 4
        else:
            raise ValueError(f"unsupported dataspace version {version}")
        dims = struct.unpack_from("<" + "Q" * rank, payload, cursor)
        if flags & 1:
            maxdims = struct.unpack_from("<" + "Q" * rank, payload, cursor + 8 * rank)
            for dim, maxdim in zip(dims, maxdims):
                if maxdim != UNDEFINED_ADDRESS and maxdim < dim:
                    raise ValueError("dataspace max dimension below current dimension")
        return tuple(dims)

    # ---------------------------------------------------------- attributes
    def _global_heap_object(self, collection: int, index: int) -> bytes:
        header = self.read(collection, 16)
        if header[:4] != b"GCOL" or header[4] != 1:
            raise ValueError(f"bad global heap collection at {collection}")
        size = u64(header, 8)
        body = self.read(collection, size)
        cursor = 16
        while cursor + 16 <= size:
            obj_index = u16(body, cursor)
            obj_size = u64(body, cursor + 8)
            if obj_index == 0:
                break
            if obj_index == index:
                return body[cursor + 16 : cursor + 16 + obj_size]
            cursor += 16 + pad8(obj_size)
        raise ValueError(f"global heap object {index} not found in {collection}")

    def _decode_attribute_value(self, dtype: bytes, dims: tuple[int, ...], data: bytes):
        count = 1
        for dim in dims:
            count *= dim
        klass = dtype[0] & 0x0F
        bits0 = dtype[1]
        size = u32(dtype, 4)
        if klass == 0:  # fixed-point
            if bits0 & 1:
                raise ValueError("big-endian integer attribute")
            signed = bool(bits0 & 0x08)
            code = {1: "b", 2: "h", 4: "i", 8: "q"}[size]
            code = code if signed else code.upper()
            values = list(struct.unpack_from("<" + code * count, data, 0))
        elif klass == 1:  # floating point
            if bits0 & 1:
                raise ValueError("big-endian float attribute")
            code = {4: "f", 8: "d"}[size]
            values = list(struct.unpack_from("<" + code * count, data, 0))
        elif klass == 3:  # fixed-length string
            values = [
                data[i * size : (i + 1) * size].split(b"\0", 1)[0].decode("utf-8")
                for i in range(count)
            ]
        elif klass == 9:  # variable-length
            if (bits0 & 0x0F) != 1:
                raise ValueError("variable-length sequence attribute is out of scope")
            values = []
            for i in range(count):
                length, collection, index = struct.unpack_from("<IQI", data, i * 16)
                if length == 0:
                    values.append("")
                    continue
                blob = self._global_heap_object(collection, index)
                values.append(blob[:length].decode("utf-8"))
        else:
            return None
        return values[0] if not dims else values

    def attributes(self, messages: list[tuple[int, int, bytes]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for kind, flags, payload in messages:
            if kind != MSG_ATTRIBUTE:
                continue
            version = payload[0]
            name_size, dtype_size, space_size = struct.unpack_from("<HHH", payload, 2)
            if version == 1:
                cursor = 8
                name = payload[cursor : cursor + name_size]
                cursor += pad8(name_size)
                dtype = payload[cursor : cursor + dtype_size]
                cursor += pad8(dtype_size)
                space = payload[cursor : cursor + space_size]
                cursor += pad8(space_size)
            elif version in (2, 3):
                cursor = 8 if version == 2 else 9
                if payload[1] & 0x03:
                    continue  # shared datatype/dataspace: not needed here
                name = payload[cursor : cursor + name_size]
                cursor += name_size
                dtype = payload[cursor : cursor + dtype_size]
                cursor += dtype_size
                space = payload[cursor : cursor + space_size]
                cursor += space_size
            else:
                raise ValueError(f"unsupported attribute message version {version}")
            key = name.split(b"\0", 1)[0].decode("utf-8")
            if space[0] == 1:
                rank = space[1]
                dims = tuple(struct.unpack_from("<" + "Q" * rank, space, 8))
            elif space[0] == 2:
                if space[3] == 0:
                    dims = ()
                elif space[3] == 2:
                    result[key] = None
                    continue
                else:
                    rank = space[1]
                    dims = tuple(struct.unpack_from("<" + "Q" * rank, space, 4))
            else:
                raise ValueError(f"unsupported attribute dataspace version {space[0]}")
            result[key] = self._decode_attribute_value(dtype, dims, payload[cursor:])
        return result

    # ------------------------------------------------------------ datasets
    def dataset(self, header_address: int) -> dict[str, object]:
        messages = self.messages(header_address)
        space_flags, space = self.only(messages, MSG_DATASPACE)
        dtype_flags, dtype = self.only(messages, MSG_DATATYPE)
        layout_flags, layout = self.only(messages, MSG_LAYOUT)
        if (space_flags | dtype_flags | layout_flags) & 0x02:
            raise ValueError("shared dataspace/datatype/layout message is out of scope")
        shape = self.dataspace(space)
        filters: list[tuple[int, int, tuple[int, ...]]] = []
        filter_messages = [payload for kind, _, payload in messages if kind == MSG_FILTER]
        if len(filter_messages) > 1:
            raise ValueError("multiple filter pipeline messages")
        if filter_messages:
            filters = self.filter_pipeline(filter_messages[0])
        info: dict[str, object] = {
            "shape": shape,
            "datatype": dtype,
            "filters": filters,
            "attributes": self.attributes(messages),
        }
        version = layout[0]
        if version != 3:
            raise ValueError(f"unsupported layout message version {version}")
        layout_class = layout[1]
        info["layout_class"] = layout_class
        if layout_class == 2:
            dimensionality = layout[2]
            info["chunk_btree"] = u64(layout, 3)
            sizes = struct.unpack_from("<" + "I" * dimensionality, layout, 11)
            info["chunk_shape"] = tuple(sizes[:-1])
            info["element_size"] = sizes[-1]
            if dimensionality != len(shape) + 1:
                raise ValueError("chunk dimensionality does not match dataspace rank")
        elif layout_class == 1:
            info["contiguous_address"] = u64(layout, 2)
            info["contiguous_size"] = u64(layout, 10)
        elif layout_class == 0:
            size = u16(layout, 2)
            info["compact_data"] = layout[4 : 4 + size]
        else:
            raise ValueError(f"unknown layout class {layout_class}")
        return info

    @staticmethod
    def filter_pipeline(payload: bytes) -> list[tuple[int, int, tuple[int, ...]]]:
        version, count = payload[0], payload[1]
        filters = []
        if version == 1:
            cursor = 8
        elif version == 2:
            cursor = 2
        else:
            raise ValueError(f"unsupported filter pipeline version {version}")
        for _ in range(count):
            filter_id = u16(payload, cursor)
            cursor += 2
            name_length = 0
            if version == 1 or filter_id >= 256:
                name_length = u16(payload, cursor)
                cursor += 2
            flags, nvalues = struct.unpack_from("<HH", payload, cursor)
            cursor += 4
            cursor += pad8(name_length) if version == 1 else name_length
            values = struct.unpack_from("<" + "I" * nvalues, payload, cursor)
            cursor += 4 * nvalues
            if version == 1 and nvalues % 2:
                cursor += 4
            filters.append((filter_id, flags, tuple(values)))
        return filters

    def chunks(self, btree: int, rank: int) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        visited: set[int] = set()
        key_size = 8 + 8 * (rank + 1)

        def visit(node: int, expected_level: int | None) -> None:
            if node in visited:
                raise ValueError(f"cyclic chunk B-tree at {node}")
            visited.add(node)
            header = self.read(node, 24)
            if header[:4] != b"TREE" or header[4] != 1:
                raise ValueError(f"bad raw-data chunk B-tree node at {node}")
            level = header[5]
            if expected_level is not None and level != expected_level:
                raise ValueError(f"chunk B-tree level mismatch at {node}")
            entries = u16(header, 6)
            body = self.read(node + 24, entries * (key_size + 8) + key_size)
            for index in range(entries):
                base = index * (key_size + 8)
                stored, mask = struct.unpack_from("<II", body, base)
                offsets = struct.unpack_from("<" + "Q" * (rank + 1), body, base + 8)
                child = u64(body, base + key_size)
                if level:
                    visit(child, level - 1)
                else:
                    out.append({"offsets": tuple(offsets), "address": child,
                                "stored_bytes": stored, "filter_mask": mask})

        visit(btree, None)
        return out


def validate_1d_deflate(info: dict[str, object], datatype: bytes, element_size: int) -> tuple[int, int]:
    """Assert a 1-D chunked dataset of exactly ``datatype`` whose only filter is deflate.

    Returns (length, chunk_length).
    """
    shape = tuple(info["shape"])
    if len(shape) != 1 or shape[0] <= 0:
        raise ValueError(f"expected a non-empty 1-D dataspace, got {shape}")
    dtype = bytes(info["datatype"])
    if dtype[: len(datatype)] != datatype or any(dtype[len(datatype) :]):
        raise ValueError(f"unexpected datatype {dtype.hex()} (want {datatype.hex()})")
    if info.get("layout_class") != 2:
        raise ValueError("dataset is not chunked")
    chunk = tuple(info["chunk_shape"])
    if len(chunk) != 1 or chunk[0] <= 0 or int(info["element_size"]) != element_size:
        raise ValueError(f"unexpected chunk geometry {chunk} element={info['element_size']}")
    filters = list(info["filters"])
    if len(filters) != 1 or filters[0][0] != FILTER_DEFLATE or len(filters[0][2]) != 1:
        raise ValueError(f"filter pipeline must be deflate only, got {filters}")
    return int(shape[0]), int(chunk[0])


def chunk_plan_1d(chunks: list[dict[str, object]], length: int, chunk_length: int) -> list[dict[str, int]]:
    """Validate the exact 1-D chunk grid and return chunks sorted by element offset."""
    expected = {(start, 0) for start in range(0, length, chunk_length)}
    offsets = [tuple(item["offsets"]) for item in chunks]
    if len(offsets) != len(set(offsets)) or set(offsets) != expected:
        raise ValueError(
            f"chunk grid mismatch: expected {len(expected)} chunks, got {len(offsets)} "
            f"(missing={sorted(expected - set(offsets))[:4]} extra={sorted(set(offsets) - expected)[:4]})"
        )
    plan = []
    for item in sorted(chunks, key=lambda entry: entry["offsets"]):
        if int(item["filter_mask"]) != 0:
            raise ValueError("chunk skipped a filter (nonzero filter mask)")
        if int(item["stored_bytes"]) <= 0:
            raise ValueError("chunk with zero stored bytes")
        start = int(item["offsets"][0])
        plan.append({
            "element_offset": start,
            "valid_elements": min(chunk_length, length - start),
            "address": int(item["address"]),
            "stored_bytes": int(item["stored_bytes"]),
        })
    return plan


def inflate_exact(payload: bytes, expected_length: int) -> bytes:
    """zlib-decompress one deflate-filtered chunk and require exact framing."""
    decompressor = zlib.decompressobj()
    try:
        data = decompressor.decompress(payload)
        data += decompressor.flush()
    except zlib.error as exc:
        raise ValueError(f"corrupt deflate chunk: {exc}") from exc
    if not decompressor.eof:
        raise ValueError("deflate stream did not terminate")
    if decompressor.unused_data.strip(b"\0"):
        raise ValueError("unexpected trailing bytes after deflate stream")
    if len(data) != expected_length:
        raise ValueError(f"inflated length {len(data)} != expected {expected_length}")
    return data
