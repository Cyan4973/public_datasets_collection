#!/usr/bin/env python3
"""Pure-standard-library reader for the Bosch CNC_Machining vibration HDF5 files.

Scope is deliberately narrow: exactly the structures written by the h5py/HDF5
1.8-style defaults used for ``data/Mxx/OPxx/<label>/*.h5`` in
https://github.com/boschresearch/CNC_Machining:

* superblock version 0 with 8-byte offsets and lengths, base address 0
* a symbol-table root group (version-1 B-tree node type 0, local heap, SNOD)
* version-1 object headers, including continuation messages (0x0010)
* dataspace message version 1 or 2, rank 2
* datatype class 1 (IEEE floating point), little-endian, 4 or 8 bytes, with
  the standard IEEE 754 binary32/binary64 field layout, or datatype class 0
  (two's-complement signed fixed point), little-endian, 1/2/4/8 bytes, full
  precision and zero bit offset.  The upstream files use float32, float64 or
  int64 containers (chosen per file by the publisher's export; mostly float
  for 2019 runs and int64 for 2020/2021 runs) for the same integer counts.
* filter pipeline message version 1 or 2 with only deflate (id 1) and/or
  shuffle (id 2); any other filter (fletcher32, szip, n-bit, scale-offset,
  third-party) is rejected
* data layout message version 3, chunked (class 2) with a version-1 B-tree
  (node type 1) chunk index, or contiguous (class 1) without filters

Anything outside this scope raises ``H5Error`` instead of guessing.  The
decoder returns the dataset as raw little-endian bytes in C (row-major)
order, exactly as ``h5py``'s ``f['vibration_data'][:]`` would materialize it,
together with the ``array`` typecode that reinterprets those bytes.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

SIGNATURE = b"\x89HDF\r\n\x1a\n"
UNDEF = 0xFFFFFFFFFFFFFFFF

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
MSG_MTIME_OLD = 0x000E

FILTER_DEFLATE = 1
FILTER_SHUFFLE = 2
SUPPORTED_FILTERS = {FILTER_DEFLATE: "deflate", FILTER_SHUFFLE: "shuffle"}

# (size, precision, exponent location, exponent size, mantissa location,
#  mantissa size, exponent bias, sign location)
IEEE_LAYOUTS = {
    4: (32, 23, 8, 0, 23, 127, 31),
    8: (64, 52, 11, 0, 52, 1023, 63),
}


class H5Error(ValueError):
    """Raised when a file deviates from the supported HDF5 subset."""


@dataclass
class Message:
    mtype: int
    flags: int
    data: bytes


@dataclass
class Dataset:
    name: str
    shape: tuple[int, ...]
    max_shape: tuple[int, ...] | None
    element_size: int
    typecode: str  # array-module typecode of the stored element: f, d, b, h, i, q
    layout_class: int
    chunk_shape: tuple[int, ...] | None
    btree_address: int | None
    data_address: int | None
    data_size: int | None
    filters: list[tuple[int, int, tuple[int, ...]]] = field(default_factory=list)
    message_types: list[int] = field(default_factory=list)
    attribute_count: int = 0
    continuation_count: int = 0


@dataclass
class Decoded:
    dataset: Dataset
    raw: bytes  # little-endian IEEE values, C order, len == prod(shape) * element_size
    chunk_count: int
    root_links: list[str]


class Reader:
    def __init__(self, buf: bytes):
        self.buf = buf
        self.size = len(buf)

    def read(self, address: int, length: int) -> bytes:
        if address < 0 or length < 0 or address + length > self.size:
            raise H5Error(f"read [{address}, {address + length}) outside file of {self.size} bytes")
        return self.buf[address : address + length]

    # ------------------------------------------------------------------ superblock
    def superblock(self) -> tuple[int, int, int]:
        head = self.read(0, 96)
        if head[:8] != SIGNATURE:
            raise H5Error("missing HDF5 signature at offset 0")
        sb_v, fs_v, root_v, _r, shared_v, osize, lsize = struct.unpack_from("<7B", head, 8)
        if sb_v != 0 or fs_v != 0 or root_v != 0 or shared_v != 0:
            raise H5Error(f"unsupported superblock versions {sb_v}/{fs_v}/{root_v}/{shared_v}")
        if osize != 8 or lsize != 8:
            raise H5Error(f"unsupported offset/length sizes {osize}/{lsize}")
        base, _free, eof, _driver = struct.unpack_from("<4Q", head, 24)
        if base != 0:
            raise H5Error(f"nonzero base address {base}")
        if eof != self.size:
            raise H5Error(f"superblock end-of-file address {eof} != file size {self.size}")
        _name_off, root_oh, cache_type, _res = struct.unpack_from("<QQII", head, 56)
        if cache_type != 1:
            raise H5Error(f"root symbol-table entry cache type {cache_type} != 1")
        btree, heap = struct.unpack_from("<QQ", head, 80)
        return root_oh, btree, heap

    # --------------------------------------------------------------- object header
    def object_header(self, address: int) -> tuple[list[Message], int]:
        prefix = self.read(address, 16)
        version, _res, nmsgs, _refs, hsize = struct.unpack_from("<BBHII", prefix, 0)
        if version != 1:
            raise H5Error(f"object header at {address} has version {version}, expected 1")
        blocks = [(address + 16, hsize)]
        seen: set[tuple[int, int]] = set()
        messages: list[Message] = []
        continuations = 0
        while blocks and len(messages) < nmsgs:
            start, size = blocks.pop(0)
            if (start, size) in seen:
                raise H5Error("object header continuation loop")
            seen.add((start, size))
            block = self.read(start, size)
            pos = 0
            while pos + 8 <= size and len(messages) < nmsgs:
                mtype, msize, mflags = struct.unpack_from("<HHB", block, pos)
                body = block[pos + 8 : pos + 8 + msize]
                if len(body) != msize:
                    raise H5Error(f"truncated message {mtype:#06x} in object header at {address}")
                messages.append(Message(mtype, mflags, body))
                if mtype == MSG_CONTINUATION:
                    cont_addr, cont_len = struct.unpack_from("<QQ", body, 0)
                    blocks.append((cont_addr, cont_len))
                    continuations += 1
                pos += 8 + msize
        if len(messages) != nmsgs:
            raise H5Error(f"object header at {address}: found {len(messages)} of {nmsgs} messages")
        return messages, continuations

    # ----------------------------------------------------------------- root group
    def root_links(self, btree: int, heap: int) -> dict[str, int]:
        hdr = self.read(heap, 32)
        if hdr[:4] != b"HEAP" or hdr[4] != 0:
            raise H5Error("root local heap signature/version mismatch")
        data_size, _free, data_addr = struct.unpack_from("<QQQ", hdr, 8)
        heap_data = self.read(data_addr, data_size)

        def name_at(offset: int) -> str:
            end = heap_data.find(b"\x00", offset)
            if end < 0:
                raise H5Error("unterminated link name in local heap")
            return heap_data[offset:end].decode("ascii")

        links: dict[str, int] = {}

        def walk(node: int, depth: int) -> None:
            if depth > 16:
                raise H5Error("group B-tree too deep")
            head = self.read(node, 24)
            if head[:4] != b"TREE":
                raise H5Error(f"missing TREE signature at {node}")
            node_type, level, used = struct.unpack_from("<BBH", head, 4)
            if node_type != 0:
                raise H5Error(f"group B-tree node type {node_type} != 0")
            body = self.read(node + 24, (2 * used + 1) * 8)
            for i in range(used):
                (child,) = struct.unpack_from("<Q", body, 8 + 16 * i)
                if level > 0:
                    walk(child, depth + 1)
                    continue
                snod = self.read(child, 8)
                if snod[:4] != b"SNOD" or snod[4] != 1:
                    raise H5Error(f"missing SNOD v1 at {child}")
                (nsym,) = struct.unpack_from("<H", snod, 6)
                table = self.read(child + 8, nsym * 40)
                for k in range(nsym):
                    name_off, oh_addr, _cache, _r = struct.unpack_from("<QQII", table, 40 * k)
                    name = name_at(name_off)
                    if name in links:
                        raise H5Error(f"duplicate root link {name!r}")
                    links[name] = oh_addr

        walk(btree, 0)
        return links

    # -------------------------------------------------------------------- dataset
    def dataset(self, name: str, address: int) -> Dataset:
        messages, continuations = self.object_header(address)
        shape = max_shape = None
        element_size = None
        typecode = None
        layout = None
        filters: list[tuple[int, int, tuple[int, ...]]] = []
        have_filter_msg = False
        attributes = 0
        for msg in messages:
            if msg.flags & 0x02:
                raise H5Error(f"shared object header message {msg.mtype:#06x} is not supported")
            if msg.mtype == MSG_DATASPACE:
                shape, max_shape = parse_dataspace(msg.data)
            elif msg.mtype == MSG_DATATYPE:
                typecode, element_size = parse_datatype(msg.data)
            elif msg.mtype == MSG_LAYOUT:
                layout = parse_layout(msg.data)
            elif msg.mtype == MSG_FILTER:
                if have_filter_msg:
                    raise H5Error("multiple filter pipeline messages")
                have_filter_msg = True
                filters = parse_filter_pipeline(msg.data)
            elif msg.mtype == MSG_ATTRIBUTE:
                attributes += 1
            elif msg.mtype in (MSG_NIL, MSG_FILL_OLD, MSG_FILL, MSG_CONTINUATION, MSG_MTIME, MSG_MTIME_OLD):
                pass
            else:
                raise H5Error(f"unexpected object header message type {msg.mtype:#06x} in {name!r}")
        if shape is None or element_size is None or typecode is None or layout is None:
            raise H5Error(f"dataset {name!r} lacks dataspace, datatype or layout message")
        layout_class, chunk_shape, btree, data_addr, data_size = layout
        if layout_class == 2:
            assert chunk_shape is not None
            if len(chunk_shape) != len(shape) + 1:
                raise H5Error(f"chunk dimensionality {len(chunk_shape)} != rank+1 for shape {shape}")
            if chunk_shape[-1] != element_size:
                raise H5Error(f"chunk element size {chunk_shape[-1]} != datatype size {element_size}")
            if any(c <= 0 for c in chunk_shape):
                raise H5Error(f"invalid chunk shape {chunk_shape}")
        elif layout_class == 1:
            if filters:
                raise H5Error("contiguous dataset with a filter pipeline")
        for filter_id, _flags, _values in filters:
            if filter_id not in SUPPORTED_FILTERS:
                raise H5Error(f"unsupported HDF5 filter id {filter_id}")
        return Dataset(
            name=name,
            shape=shape,
            max_shape=max_shape,
            element_size=element_size,
            typecode=typecode,
            layout_class=layout_class,
            chunk_shape=chunk_shape,
            btree_address=btree,
            data_address=data_addr,
            data_size=data_size,
            filters=filters,
            message_types=[m.mtype for m in messages],
            attribute_count=attributes,
            continuation_count=continuations,
        )

    # --------------------------------------------------------------- chunk index
    def chunk_entries(self, btree: int, ndims: int) -> list[tuple[int, int, tuple[int, ...], int]]:
        """Return (stored_size, filter_mask, offsets, address) for every chunk."""
        key_size = 8 + 8 * ndims
        out: list[tuple[int, int, tuple[int, ...], int]] = []
        seen_nodes: set[int] = set()

        def walk(node: int, expect_level: int | None, depth: int) -> None:
            if depth > 32 or node in seen_nodes:
                raise H5Error("chunk B-tree loop or excessive depth")
            seen_nodes.add(node)
            head = self.read(node, 24)
            if head[:4] != b"TREE":
                raise H5Error(f"missing TREE signature at chunk node {node}")
            node_type, level, used = struct.unpack_from("<BBH", head, 4)
            if node_type != 1:
                raise H5Error(f"chunk B-tree node type {node_type} != 1")
            if expect_level is not None and level != expect_level:
                raise H5Error(f"chunk B-tree level {level} != expected {expect_level}")
            body = self.read(node + 24, used * (key_size + 8) + key_size)
            pos = 0
            for _ in range(used):
                stored, mask = struct.unpack_from("<II", body, pos)
                offsets = struct.unpack_from(f"<{ndims}Q", body, pos + 8)
                (child,) = struct.unpack_from("<Q", body, pos + key_size)
                pos += key_size + 8
                if level > 0:
                    walk(child, level - 1, depth + 1)
                else:
                    out.append((stored, mask, tuple(offsets), child))

        walk(btree, None, 0)
        return out


def parse_dataspace(body: bytes) -> tuple[tuple[int, ...], tuple[int, ...] | None]:
    version, rank, flags = struct.unpack_from("<BBB", body, 0)
    if version == 1:
        pos = 8
        if flags & 0x02:
            raise H5Error("dataspace permutation index is not supported")
    elif version == 2:
        pos = 4
        if body[3] != 1:
            raise H5Error(f"dataspace type {body[3]} is not simple")
    else:
        raise H5Error(f"unsupported dataspace version {version}")
    dims = tuple(struct.unpack_from(f"<{rank}Q", body, pos)) if rank else ()
    pos += 8 * rank
    max_dims = tuple(struct.unpack_from(f"<{rank}Q", body, pos)) if flags & 0x01 else None
    return dims, max_dims


INT_TYPECODES = {1: "b", 2: "h", 4: "i", 8: "q"}


def parse_datatype(body: bytes) -> tuple[str, int]:
    """Return (array typecode, element size) for the supported numeric types."""
    class_version = body[0]
    dclass = class_version & 0x0F
    version = class_version >> 4
    if version not in (1, 2, 3):
        raise H5Error(f"unsupported datatype version {version}")
    bits0, bits1, bits2 = body[1], body[2], body[3]
    (size,) = struct.unpack_from("<I", body, 4)
    if dclass == 0:
        if size not in INT_TYPECODES:
            raise H5Error(f"unsupported fixed-point size {size}")
        if bits0 & 0x01:
            raise H5Error("fixed-point datatype is not little-endian")
        if bits0 & 0x06:
            raise H5Error("fixed-point datatype has non-zero padding bits")
        if not bits0 & 0x08:
            raise H5Error("fixed-point datatype is unsigned; only signed counts are expected")
        if bits1 or bits2 or bits0 & 0xF0:
            raise H5Error("fixed-point datatype has unexpected class bit fields")
        bit_offset, precision = struct.unpack_from("<HH", body, 8)
        if bit_offset != 0 or precision != 8 * size:
            raise H5Error(f"fixed-point offset/precision {bit_offset}/{precision} for size {size}")
        return INT_TYPECODES[size], size
    if dclass != 1:
        raise H5Error(f"datatype class {dclass} is neither fixed point nor IEEE floating point")
    if size not in IEEE_LAYOUTS:
        raise H5Error(f"unsupported floating-point size {size}")
    if bits0 & 0x01 or bits0 & 0x40:
        raise H5Error("floating-point datatype is not little-endian")
    if bits0 & 0x0E:
        raise H5Error("floating-point datatype has non-zero padding bits")
    if (bits0 >> 4) & 0x03 != 2:
        raise H5Error("floating-point mantissa normalization is not 'implied MSB'")
    bit_offset, precision, exp_loc, exp_size, mant_loc, mant_size, bias = struct.unpack_from("<HHBBBBI", body, 8)
    want = IEEE_LAYOUTS[size]
    got = (precision, exp_loc, exp_size, mant_loc, mant_size, bias, bits1)
    if bit_offset != 0 or got != want:
        raise H5Error(f"floating-point field layout {got} (offset {bit_offset}) is not IEEE binary{size * 8}")
    return ("f" if size == 4 else "d"), size


def parse_layout(body: bytes) -> tuple[int, tuple[int, ...] | None, int | None, int | None, int | None]:
    version = body[0]
    if version != 3:
        raise H5Error(f"unsupported data layout version {version}")
    layout_class = body[1]
    if layout_class == 2:
        ndims = body[2]
        (btree,) = struct.unpack_from("<Q", body, 3)
        chunk = tuple(struct.unpack_from(f"<{ndims}I", body, 11))
        return 2, chunk, btree, None, None
    if layout_class == 1:
        address, size = struct.unpack_from("<QQ", body, 2)
        return 1, None, None, address, size
    raise H5Error(f"unsupported data layout class {layout_class}")


def parse_filter_pipeline(body: bytes) -> list[tuple[int, int, tuple[int, ...]]]:
    version, nfilters = body[0], body[1]
    filters: list[tuple[int, int, tuple[int, ...]]] = []
    if version == 1:
        pos = 8
        for _ in range(nfilters):
            filter_id, name_len, flags, nvalues = struct.unpack_from("<HHHH", body, pos)
            pos += 8 + name_len
            values = struct.unpack_from(f"<{nvalues}I", body, pos)
            pos += 4 * nvalues + (4 if nvalues % 2 else 0)
            filters.append((filter_id, flags, tuple(values)))
    elif version == 2:
        pos = 2
        for _ in range(nfilters):
            (filter_id,) = struct.unpack_from("<H", body, pos)
            pos += 2
            name_len = 0
            if filter_id >= 256:
                (name_len,) = struct.unpack_from("<H", body, pos)
                pos += 2
            flags, nvalues = struct.unpack_from("<HH", body, pos)
            pos += 4 + name_len
            values = struct.unpack_from(f"<{nvalues}I", body, pos)
            pos += 4 * nvalues
            filters.append((filter_id, flags, tuple(values)))
    else:
        raise H5Error(f"unsupported filter pipeline version {version}")
    return filters


def unshuffle(data: bytes, element_size: int) -> bytes:
    count = len(data) // element_size
    out = bytearray(len(data))
    for b in range(element_size):
        out[b : count * element_size : element_size] = data[b * count : (b + 1) * count]
    out[count * element_size :] = data[count * element_size :]
    return bytes(out)


def apply_filters(data: bytes, filters: list[tuple[int, int, tuple[int, ...]]], mask: int,
                  element_size: int, expected: int) -> bytes:
    for index in range(len(filters) - 1, -1, -1):
        if mask & (1 << index):
            continue
        filter_id = filters[index][0]
        if filter_id == FILTER_DEFLATE:
            dec = zlib.decompressobj()
            data = dec.decompress(data, expected + 1)
            if dec.unconsumed_tail or not dec.eof:
                raise H5Error("deflate chunk does not end exactly at its stream end")
        elif filter_id == FILTER_SHUFFLE:
            data = unshuffle(data, element_size)
        else:  # pragma: no cover - rejected earlier
            raise H5Error(f"unsupported filter id {filter_id}")
    if mask >> len(filters):
        raise H5Error(f"chunk filter mask {mask:#x} references undefined filters")
    return data


def decode_dataset(reader: Reader, ds: Dataset) -> tuple[bytes, int]:
    es = ds.element_size
    total = 1
    for d in ds.shape:
        total *= d
    if ds.layout_class == 1:
        assert ds.data_address is not None and ds.data_size is not None
        if ds.data_size != total * es:
            raise H5Error(f"contiguous data size {ds.data_size} != {total * es}")
        return reader.read(ds.data_address, ds.data_size), 0
    assert ds.chunk_shape is not None and ds.btree_address is not None
    if len(ds.shape) != 2:
        raise H5Error(f"chunk assembly supports rank 2 only, got shape {ds.shape}")
    rows, cols = ds.shape
    crows, ccols = ds.chunk_shape[0], ds.chunk_shape[1]
    chunk_bytes = crows * ccols * es
    entries = reader.chunk_entries(ds.btree_address, len(ds.chunk_shape))
    expected_offsets = {(r, c) for r in range(0, rows, crows) for c in range(0, cols, ccols)}
    got_offsets = [(o[0], o[1]) for _s, _m, o, _a in entries]
    if len(got_offsets) != len(set(got_offsets)) or set(got_offsets) != expected_offsets:
        raise H5Error(
            f"chunk grid mismatch: expected {len(expected_offsets)} chunks, index has {len(got_offsets)}"
        )
    out = bytearray(total * es)
    mv = memoryview(out)
    for stored, mask, offsets, address in entries:
        if offsets[2] != 0:
            raise H5Error(f"nonzero element-dimension chunk offset {offsets}")
        raw = reader.read(address, stored)
        payload = apply_filters(raw, ds.filters, mask, es, chunk_bytes) if ds.filters else raw
        if len(payload) != chunk_bytes:
            raise H5Error(f"decoded chunk size {len(payload)} != {chunk_bytes} at offsets {offsets}")
        r0, c0 = offsets[0], offsets[1]
        nr = min(crows, rows - r0)
        nc = min(ccols, cols - c0)
        if ccols == 1:
            # Single-column chunks (the layout used upstream): strided byte scatter.
            start = (r0 * cols + c0) * es
            stop = start + (nr - 1) * cols * es + es
            for b in range(es):
                out[start + b : stop : cols * es] = payload[b : nr * es : es]
        else:
            for i in range(nr):
                src = (i * ccols) * es
                dst = ((r0 + i) * cols + c0) * es
                mv[dst : dst + nc * es] = payload[src : src + nc * es]
    return bytes(out), len(entries)


def decode_file(buf: bytes, dataset_name: str = "vibration_data") -> Decoded:
    reader = Reader(buf)
    root_oh, btree, heap = reader.superblock()
    root_msgs, _ = reader.object_header(root_oh)
    stab = [m for m in root_msgs if m.mtype == MSG_SYMBOL_TABLE]
    if len(stab) != 1:
        raise H5Error("root object header lacks exactly one symbol-table message")
    st_btree, st_heap = struct.unpack_from("<QQ", stab[0].data, 0)
    if (st_btree, st_heap) != (btree, heap):
        raise H5Error("root symbol-table message disagrees with superblock scratch pad")
    links = reader.root_links(btree, heap)
    if dataset_name not in links:
        raise H5Error(f"root group lacks {dataset_name!r}; links={sorted(links)}")
    ds = reader.dataset(dataset_name, links[dataset_name])
    raw, nchunks = decode_dataset(reader, ds)
    return Decoded(dataset=ds, raw=raw, chunk_count=nchunks, root_links=sorted(links))
