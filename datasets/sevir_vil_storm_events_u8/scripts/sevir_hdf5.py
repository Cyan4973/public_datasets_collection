#!/usr/bin/env python3
"""Dependency-free reader for the metadata of SEVIR VIL HDF5 containers.

SEVIR STORMEVENTS VIL files are HDF5 files with a version-0 superblock and a
classic (symbol-table) root group holding exactly two datasets:

* ``vil``: uint8, dataspace ``(N, 384, 384, 49)``, contiguous, unfiltered,
  stored at file offset 2048 in C order, so event ``i`` occupies exactly
  ``384*384*49 = 7,225,344`` bytes starting at ``2048 + i*7,225,344``;
* ``id``: fixed-length ASCII strings, dataspace ``(N,)``, contiguous, stored
  after the ``vil`` payload near the end of the file.

The recipe never downloads whole containers.  It range-fetches the metadata
head (bytes ``[0, 2048)``) and the metadata tail (from the end of the ``vil``
payload to EOF) and parses them here.  Every structure this module touches
must lie inside one of the fetched segments; anything else is a hard error,
so a changed container layout is rejected instead of being guessed at.

Only the HDF5 features that SEVIR uses are implemented: superblock v0,
symbol-table groups (v1 B-tree type 0, local heap, SNOD), version-1 object
headers with continuation blocks, dataspace v1/v2, fixed-point and string
datatypes, data-layout v3 (contiguous/compact).  A filter-pipeline message on
either dataset is a hard error.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

SIGNATURE = b"\x89HDF\r\n\x1a\n"
UNDEFINED = 0xFFFFFFFFFFFFFFFF

EVENT_SHAPE = (384, 384, 49)
EVENT_BYTES = EVENT_SHAPE[0] * EVENT_SHAPE[1] * EVENT_SHAPE[2]  # 7,225,344
VIL_DATA_ADDRESS = 2048
HEAD_BYTES = VIL_DATA_ADDRESS  # metadata head = [0, 2048)

MSG_NIL = 0x0000
MSG_DATASPACE = 0x0001
MSG_DATATYPE = 0x0003
MSG_FILL_OLD = 0x0004
MSG_FILL = 0x0005
MSG_LAYOUT = 0x0008
MSG_FILTER = 0x000B
MSG_ATTRIBUTE = 0x000C
MSG_CONTINUATION = 0x0010
MSG_SYMBOL_TABLE = 0x0011
MSG_MTIME = 0x0012


class HDF5LayoutError(ValueError):
    """Raised when the container deviates from the expected SEVIR layout."""


class Segments:
    """Sparse view of a file assembled from fetched byte ranges."""

    def __init__(self, file_size: int):
        self.file_size = file_size
        self.parts: list[tuple[int, bytes]] = []

    def add(self, offset: int, data: bytes) -> None:
        if offset < 0 or offset + len(data) > self.file_size:
            raise HDF5LayoutError(f"segment [{offset}, {offset + len(data)}) outside file of {self.file_size} bytes")
        self.parts.append((offset, bytes(data)))

    def read(self, address: int, length: int) -> bytes:
        for offset, data in self.parts:
            if offset <= address and address + length <= offset + len(data):
                start = address - offset
                return data[start : start + length]
        raise HDF5LayoutError(f"bytes [{address}, {address + length}) are not inside any fetched segment")


@dataclass
class Superblock:
    offset_size: int
    length_size: int
    base_address: int
    eof_address: int
    root_object_header: int
    root_btree: int
    root_heap: int


@dataclass
class Message:
    mtype: int
    flags: int
    data: bytes


@dataclass
class DatasetInfo:
    name: str
    object_header: int
    shape: tuple[int, ...]
    max_shape: tuple[int, ...] | None
    dtype_class: int
    dtype_size: int
    dtype_signed: bool | None
    dtype_byte_order: str | None
    dtype_precision: int | None
    dtype_offset: int | None
    string_padding: int | None
    layout_class: int
    data_address: int
    data_size: int
    has_filter_pipeline: bool
    message_types: list[int] = field(default_factory=list)


def _uint(raw: bytes, size: int) -> int:
    if size == 8:
        return struct.unpack("<Q", raw)[0]
    if size == 4:
        return struct.unpack("<I", raw)[0]
    if size == 2:
        return struct.unpack("<H", raw)[0]
    raise HDF5LayoutError(f"unsupported integer size {size}")


def parse_superblock(seg: Segments) -> Superblock:
    head = seg.read(0, 96)
    if head[:8] != SIGNATURE:
        raise HDF5LayoutError("missing HDF5 signature at offset 0")
    version, freespace_v, root_v, _r, shared_v, osize, lsize = struct.unpack_from("<7B", head, 8)
    if version != 0 or freespace_v != 0 or root_v != 0 or shared_v != 0:
        raise HDF5LayoutError(f"unexpected superblock versions {version}/{freespace_v}/{root_v}/{shared_v}")
    if osize != 8 or lsize != 8:
        raise HDF5LayoutError(f"unexpected offset/length sizes {osize}/{lsize}")
    base, _freespace, eof, _driver = struct.unpack_from("<4Q", head, 24)
    if base != 0:
        raise HDF5LayoutError(f"nonzero base address {base}")
    if eof != seg.file_size:
        raise HDF5LayoutError(f"superblock EOF {eof} != object size {seg.file_size}")
    _name_off, root_oh, cache_type, _res = struct.unpack_from("<QQII", head, 56)
    if cache_type != 1:
        raise HDF5LayoutError(f"root symbol-table entry cache type {cache_type} != 1")
    btree, heap = struct.unpack_from("<QQ", head, 80)
    return Superblock(osize, lsize, base, eof, root_oh, btree, heap)


def read_object_header(seg: Segments, address: int) -> list[Message]:
    prefix = seg.read(address, 16)
    version, _res, nmsgs, _refs, hsize = struct.unpack_from("<BBHII", prefix, 0)
    if version != 1:
        raise HDF5LayoutError(f"object header at {address} has version {version}, expected 1")
    blocks = [(address + 16, hsize)]
    messages: list[Message] = []
    seen_blocks = set()
    while blocks and len(messages) < nmsgs:
        start, size = blocks.pop(0)
        if (start, size) in seen_blocks:
            raise HDF5LayoutError("object header continuation loop")
        seen_blocks.add((start, size))
        block = seg.read(start, size)
        pos = 0
        while pos + 8 <= size and len(messages) < nmsgs:
            mtype, msize, mflags = struct.unpack_from("<HHB", block, pos)
            body = block[pos + 8 : pos + 8 + msize]
            if len(body) != msize:
                raise HDF5LayoutError(f"truncated message type {mtype:#x} in object header at {address}")
            messages.append(Message(mtype, mflags, body))
            if mtype == MSG_CONTINUATION:
                cont_addr, cont_len = struct.unpack_from("<QQ", body, 0)
                blocks.append((cont_addr, cont_len))
            pos += 8 + msize
    if len(messages) != nmsgs:
        raise HDF5LayoutError(f"object header at {address}: found {len(messages)} of {nmsgs} messages")
    return messages


def _parse_dataspace(body: bytes) -> tuple[tuple[int, ...], tuple[int, ...] | None]:
    version, rank, flags = struct.unpack_from("<BBB", body, 0)
    if version == 1:
        pos = 8
    elif version == 2:
        pos = 4
    else:
        raise HDF5LayoutError(f"unsupported dataspace version {version}")
    dims = tuple(struct.unpack_from(f"<{rank}Q", body, pos)) if rank else ()
    pos += 8 * rank
    max_dims = None
    if flags & 1:
        max_dims = tuple(struct.unpack_from(f"<{rank}Q", body, pos))
    return dims, max_dims


def _parse_layout(body: bytes) -> tuple[int, int, int]:
    version = body[0]
    if version != 3:
        raise HDF5LayoutError(f"unsupported data layout version {version}")
    layout_class = body[1]
    if layout_class == 1:
        address, size = struct.unpack_from("<QQ", body, 2)
        return layout_class, address, size
    if layout_class == 0:
        (size,) = struct.unpack_from("<H", body, 2)
        return layout_class, -1, size
    raise HDF5LayoutError(f"unsupported layout class {layout_class} (chunked data is not expected in SEVIR VIL)")


def parse_dataset(seg: Segments, name: str, address: int) -> DatasetInfo:
    messages = read_object_header(seg, address)
    shape = max_shape = None
    dtype = None
    layout = None
    has_filter = False
    for msg in messages:
        if msg.mtype == MSG_DATASPACE:
            shape, max_shape = _parse_dataspace(msg.data)
        elif msg.mtype == MSG_DATATYPE:
            dtype = msg.data
        elif msg.mtype == MSG_LAYOUT:
            layout = _parse_layout(msg.data)
        elif msg.mtype == MSG_FILTER:
            has_filter = True
    if shape is None or dtype is None or layout is None:
        raise HDF5LayoutError(f"dataset {name!r} lacks dataspace, datatype or layout message")
    class_version = dtype[0]
    dclass = class_version & 0x0F
    bits0 = dtype[1]
    (dsize,) = struct.unpack_from("<I", dtype, 4)
    signed = byte_order = precision = bit_offset = padding = None
    if dclass == 0:
        byte_order = "big" if bits0 & 1 else "little"
        signed = bool(bits0 & 0x08)
        bit_offset, precision = struct.unpack_from("<HH", dtype, 8)
    elif dclass == 3:
        padding = bits0 & 0x0F
    return DatasetInfo(
        name=name,
        object_header=address,
        shape=tuple(shape),
        max_shape=tuple(max_shape) if max_shape else None,
        dtype_class=dclass,
        dtype_size=dsize,
        dtype_signed=signed,
        dtype_byte_order=byte_order,
        dtype_precision=precision,
        dtype_offset=bit_offset,
        string_padding=padding,
        layout_class=layout[0],
        data_address=layout[1],
        data_size=layout[2],
        has_filter_pipeline=has_filter,
        message_types=[m.mtype for m in messages],
    )


def root_group_entries(seg: Segments, sb: Superblock) -> dict[str, int]:
    heap = seg.read(sb.root_heap, 32)
    if heap[:4] != b"HEAP" or heap[4] != 0:
        raise HDF5LayoutError("root local heap signature/version mismatch")
    heap_data_size, _free, heap_data_addr = struct.unpack_from("<QQQ", heap, 8)
    heap_data = seg.read(heap_data_addr, heap_data_size)

    def name_at(offset: int) -> str:
        end = heap_data.index(b"\x00", offset)
        return heap_data[offset:end].decode("ascii")

    entries: dict[str, int] = {}

    def walk(node_addr: int, depth: int) -> None:
        if depth > 8:
            raise HDF5LayoutError("group B-tree too deep")
        hdr = seg.read(node_addr, 24)
        if hdr[:4] != b"TREE":
            raise HDF5LayoutError(f"missing TREE signature at {node_addr}")
        node_type, level, used = struct.unpack_from("<BBH", hdr, 4)
        if node_type != 0:
            raise HDF5LayoutError(f"group B-tree node type {node_type} != 0")
        body = seg.read(node_addr + 24, (2 * used + 1) * 8)
        children = [struct.unpack_from("<Q", body, 8 + 16 * i)[0] for i in range(used)]
        for child in children:
            if level > 0:
                walk(child, depth + 1)
                continue
            snod = seg.read(child, 8)
            if snod[:4] != b"SNOD" or snod[4] != 1:
                raise HDF5LayoutError(f"missing SNOD v1 at {child}")
            (nsym,) = struct.unpack_from("<H", snod, 6)
            table = seg.read(child + 8, nsym * 40)
            for k in range(nsym):
                name_off, oh_addr, _cache, _res = struct.unpack_from("<QQII", table, 40 * k)
                name = name_at(name_off)
                if name in entries:
                    raise HDF5LayoutError(f"duplicate root link {name!r}")
                entries[name] = oh_addr

    walk(sb.root_btree, 0)
    return entries


@dataclass
class Container:
    file_size: int
    event_count: int
    vil: DatasetInfo
    id_ds: DatasetInfo
    tail_offset: int
    entries: dict[str, int]


def tail_offset_from_head(head: bytes, file_size: int) -> tuple[int, int]:
    """Return (event_count, tail_offset) using only the 2048-byte head."""
    seg = Segments(file_size)
    seg.add(0, head)
    sb = parse_superblock(seg)
    entries = root_group_entries(seg, sb)
    if sorted(entries) != ["id", "vil"]:
        raise HDF5LayoutError(f"root links {sorted(entries)} != ['id', 'vil']")
    vil = parse_dataset(seg, "vil", entries["vil"])
    check_vil(vil, file_size)
    return vil.shape[0], vil.data_address + vil.data_size


def check_vil(vil: DatasetInfo, file_size: int) -> None:
    if len(vil.shape) != 4 or tuple(vil.shape[1:]) != EVENT_SHAPE or vil.shape[0] < 1:
        raise HDF5LayoutError(f"vil shape {vil.shape} is not (N, 384, 384, 49)")
    if vil.max_shape is not None and tuple(vil.max_shape) != tuple(vil.shape):
        raise HDF5LayoutError(f"vil max shape {vil.max_shape} != shape {vil.shape}")
    if not (vil.dtype_class == 0 and vil.dtype_size == 1 and vil.dtype_signed is False and vil.dtype_precision == 8 and vil.dtype_offset == 0):
        raise HDF5LayoutError(
            f"vil datatype is not unsigned 8-bit fixed point: class={vil.dtype_class} size={vil.dtype_size} signed={vil.dtype_signed} precision={vil.dtype_precision}"
        )
    if vil.has_filter_pipeline:
        raise HDF5LayoutError("vil has a filter pipeline message")
    if vil.layout_class != 1:
        raise HDF5LayoutError(f"vil layout class {vil.layout_class} is not contiguous")
    if vil.data_address != VIL_DATA_ADDRESS:
        raise HDF5LayoutError(f"vil data address {vil.data_address} != {VIL_DATA_ADDRESS}")
    if vil.data_size != vil.shape[0] * EVENT_BYTES:
        raise HDF5LayoutError(f"vil data size {vil.data_size} != N*{EVENT_BYTES}")
    if vil.data_address + vil.data_size > file_size:
        raise HDF5LayoutError("vil payload extends past EOF")


def parse_container(head: bytes, tail: bytes, tail_offset: int, file_size: int) -> Container:
    if len(head) != HEAD_BYTES:
        raise HDF5LayoutError(f"head has {len(head)} bytes, expected {HEAD_BYTES}")
    if tail_offset + len(tail) != file_size:
        raise HDF5LayoutError("tail does not end at EOF")
    seg = Segments(file_size)
    seg.add(0, head)
    seg.add(tail_offset, tail)
    sb = parse_superblock(seg)
    entries = root_group_entries(seg, sb)
    if sorted(entries) != ["id", "vil"]:
        raise HDF5LayoutError(f"root links {sorted(entries)} != ['id', 'vil']")
    vil = parse_dataset(seg, "vil", entries["vil"])
    check_vil(vil, file_size)
    if vil.data_address + vil.data_size != tail_offset:
        raise HDF5LayoutError("tail does not start exactly at the end of the vil payload")
    id_ds = parse_dataset(seg, "id", entries["id"])
    n = vil.shape[0]
    if id_ds.shape != (n,):
        raise HDF5LayoutError(f"id shape {id_ds.shape} != ({n},)")
    if id_ds.dtype_class != 3 or not (1 <= id_ds.dtype_size <= 64):
        raise HDF5LayoutError(f"id datatype class {id_ds.dtype_class} size {id_ds.dtype_size} is not a fixed string")
    if id_ds.has_filter_pipeline:
        raise HDF5LayoutError("id has a filter pipeline message")
    if id_ds.data_size != n * id_ds.dtype_size:
        raise HDF5LayoutError("id data size mismatch")
    return Container(file_size, n, vil, id_ds, tail_offset, entries)


def read_event_ids(container: Container, head: bytes, tail: bytes) -> list[str]:
    seg = Segments(container.file_size)
    seg.add(0, head)
    seg.add(container.tail_offset, tail)
    ds = container.id_ds
    if ds.layout_class == 1:
        raw = seg.read(ds.data_address, ds.data_size)
    else:
        raise HDF5LayoutError("compact id storage is not expected")
    ids = []
    for k in range(container.event_count):
        cell = raw[k * ds.dtype_size : (k + 1) * ds.dtype_size]
        text = cell.split(b"\x00", 1)[0].rstrip(b" ").decode("ascii")
        if not text:
            raise HDF5LayoutError(f"empty id at index {k}")
        ids.append(text)
    if len(set(ids)) != len(ids):
        raise HDF5LayoutError("duplicate event ids in container")
    return ids


def event_offset(file_index: int) -> int:
    return VIL_DATA_ADDRESS + file_index * EVENT_BYTES
