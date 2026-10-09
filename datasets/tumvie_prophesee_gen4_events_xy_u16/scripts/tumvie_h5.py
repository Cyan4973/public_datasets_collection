#!/usr/bin/env python3
"""Dependency-free reader for TUM-VIE event HDF5 files, from sparse byte ranges.

TUM-VIE ``<seq>-events_left.h5`` files (written by h5py with the hdf5plugin
Blosc filter) have a version-0 superblock, a classic symbol-table root group
with a group ``events`` (datasets ``p``, ``t``, ``x``, ``y``) and a dataset
``ms_to_idx``.  ``events/x`` and ``events/y`` are 1-D uint16 datasets, chunked
(chunk = 32,768 elements = 65,536 bytes) with a v1 B-tree (type 1) chunk index
and one filter: Blosc (HDF5 filter id 32001), byte-shuffle, ZSTD.

The recipe never downloads whole files (1.2-17.9 GB).  Every byte this module
reads must lie inside a fetched range kept under ``<cache>/<offset>-<length>.bin``;
a missing range raises :class:`NeedBytes` so that ``download.sh`` (curl) can fetch
it and re-run the planner.  Python never touches the network.

Only the HDF5 features the files use are implemented: superblock v0,
symbol-table groups (v1 B-tree type 0, local heap, SNOD), version-1 object
headers with continuation blocks, dataspace v1/v2, fixed-point datatype,
data-layout v3 chunked, filter pipeline v1/v2, v1 B-tree type 1.  Anything
else is a hard error, so a changed layout is rejected rather than guessed at.
"""
from __future__ import annotations

import os
import re
import struct
import subprocess
from dataclasses import dataclass, field

SIGNATURE = b"\x89HDF\r\n\x1a\n"
UNDEFINED = 0xFFFFFFFFFFFFFFFF

CHUNK_ELEMS = 32768
ELEM_SIZE = 2
CHUNK_BYTES = CHUNK_ELEMS * ELEM_SIZE  # 65,536
BLOSC_FILTER_ID = 32001
MIN_FETCH = 4096  # metadata fetch granularity (bytes)

MSG_DATASPACE = 0x0001
MSG_DATATYPE = 0x0003
MSG_LAYOUT = 0x0008
MSG_FILTER = 0x000B
MSG_CONTINUATION = 0x0010
MSG_SYMBOL_TABLE = 0x0011

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class LayoutError(ValueError):
    """The file deviates from the expected TUM-VIE layout."""


class NeedBytes(Exception):
    """A read touched bytes that are not in the sparse cache yet."""

    def __init__(self, address: int, length: int):
        super().__init__(f"need bytes [{address}, {address + length})")
        self.address = address
        self.length = length


_RANGE_RE = re.compile(r"^(\d+)-(\d+)\.bin$")


class Segments:
    """Sparse view of a remote file assembled from fetched byte ranges."""

    def __init__(self, file_size: int, cache_dir: str | None = None):
        self.file_size = file_size
        self.parts: list[tuple[int, bytes]] = []
        if cache_dir and os.path.isdir(cache_dir):
            for name in sorted(os.listdir(cache_dir)):
                m = _RANGE_RE.match(name)
                if not m:
                    continue
                off, length = int(m.group(1)), int(m.group(2))
                with open(os.path.join(cache_dir, name), "rb") as fh:
                    data = fh.read()
                if len(data) != length:
                    raise LayoutError(f"cache file {name} has {len(data)} bytes, expected {length}")
                self.add(off, data)

    def add(self, offset: int, data: bytes) -> None:
        if offset < 0 or offset + len(data) > self.file_size:
            raise LayoutError(f"segment [{offset}, {offset + len(data)}) outside file of {self.file_size} bytes")
        self.parts.append((offset, bytes(data)))

    def read(self, address: int, length: int) -> bytes:
        if address < 0 or length < 0 or address + length > self.file_size:
            raise LayoutError(f"read [{address}, {address + length}) outside file of {self.file_size} bytes")
        for offset, data in self.parts:
            if offset <= address and address + length <= offset + len(data):
                start = address - offset
                return data[start : start + length]
        raise NeedBytes(address, length)


def fetch_window(need: NeedBytes, file_size: int) -> tuple[int, int]:
    """Range to fetch for a metadata miss: at least MIN_FETCH bytes, clipped to EOF."""
    length = max(need.length, MIN_FETCH)
    end = min(file_size, need.address + length)
    return need.address, end - need.address


# --------------------------------------------------------------------------- superblock / groups
@dataclass
class Superblock:
    eof_address: int
    root_object_header: int
    root_btree: int
    root_heap: int


def parse_superblock(seg: Segments) -> Superblock:
    head = seg.read(0, 96)
    if head[:8] != SIGNATURE:
        raise LayoutError("missing HDF5 signature at offset 0")
    version, fs_v, root_v, _r, shared_v, osize, lsize = struct.unpack_from("<7B", head, 8)
    if (version, fs_v, root_v, shared_v) != (0, 0, 0, 0):
        raise LayoutError(f"unexpected superblock versions {version}/{fs_v}/{root_v}/{shared_v}")
    if osize != 8 or lsize != 8:
        raise LayoutError(f"unexpected offset/length sizes {osize}/{lsize}")
    base, _fs, eof, _drv = struct.unpack_from("<4Q", head, 24)
    if base != 0:
        raise LayoutError(f"nonzero base address {base}")
    if eof != seg.file_size:
        raise LayoutError(f"superblock EOF {eof} != file size {seg.file_size}")
    _name_off, root_oh, cache_type, _res = struct.unpack_from("<QQII", head, 56)
    if cache_type != 1:
        raise LayoutError(f"root symbol-table entry cache type {cache_type} != 1")
    btree, heap = struct.unpack_from("<QQ", head, 80)
    return Superblock(eof, root_oh, btree, heap)


@dataclass
class Message:
    mtype: int
    flags: int
    data: bytes


def read_object_header(seg: Segments, address: int) -> list[Message]:
    prefix = seg.read(address, 16)
    version, _res, nmsgs, _refs, hsize = struct.unpack_from("<BBHII", prefix, 0)
    if version != 1:
        raise LayoutError(f"object header at {address} has version {version}, expected 1")
    blocks = [(address + 16, hsize)]
    messages: list[Message] = []
    seen = set()
    while blocks and len(messages) < nmsgs:
        start, size = blocks.pop(0)
        if (start, size) in seen:
            raise LayoutError("object header continuation loop")
        seen.add((start, size))
        block = seg.read(start, size)
        pos = 0
        while pos + 8 <= size and len(messages) < nmsgs:
            mtype, msize, mflags = struct.unpack_from("<HHB", block, pos)
            body = block[pos + 8 : pos + 8 + msize]
            if len(body) != msize:
                raise LayoutError(f"truncated message {mtype:#x} in object header at {address}")
            messages.append(Message(mtype, mflags, body))
            if mtype == MSG_CONTINUATION:
                blocks.append(struct.unpack_from("<QQ", body, 0))
            pos += 8 + msize
    if len(messages) != nmsgs:
        raise LayoutError(f"object header at {address}: found {len(messages)} of {nmsgs} messages")
    return messages


def group_entries(seg: Segments, btree_addr: int, heap_addr: int) -> dict[str, int]:
    heap = seg.read(heap_addr, 32)
    if heap[:4] != b"HEAP" or heap[4] != 0:
        raise LayoutError(f"local heap signature/version mismatch at {heap_addr}")
    heap_size, _free, heap_data_addr = struct.unpack_from("<QQQ", heap, 8)
    heap_data = seg.read(heap_data_addr, heap_size)

    def name_at(off: int) -> str:
        end = heap_data.index(b"\x00", off)
        return heap_data[off:end].decode("ascii")

    entries: dict[str, int] = {}

    def walk(node: int, depth: int) -> None:
        if depth > 8:
            raise LayoutError("group B-tree too deep")
        hdr = seg.read(node, 24)
        if hdr[:4] != b"TREE":
            raise LayoutError(f"missing TREE signature at {node}")
        ntype, level, used = struct.unpack_from("<BBH", hdr, 4)
        if ntype != 0:
            raise LayoutError(f"group B-tree node type {ntype} != 0")
        body = seg.read(node + 24, (2 * used + 1) * 8)
        for i in range(used):
            child = struct.unpack_from("<Q", body, 8 + 16 * i)[0]
            if level > 0:
                walk(child, depth + 1)
                continue
            snod = seg.read(child, 8)
            if snod[:4] != b"SNOD" or snod[4] != 1:
                raise LayoutError(f"missing SNOD v1 at {child}")
            (nsym,) = struct.unpack_from("<H", snod, 6)
            table = seg.read(child + 8, nsym * 40)
            for k in range(nsym):
                name_off, oh, _cache, _res = struct.unpack_from("<QQII", table, 40 * k)
                name = name_at(name_off)
                if name in entries:
                    raise LayoutError(f"duplicate link {name!r}")
                entries[name] = oh

    walk(btree_addr, 0)
    return entries


def symbol_table_of(seg: Segments, oh_addr: int) -> tuple[int, int]:
    for msg in read_object_header(seg, oh_addr):
        if msg.mtype == MSG_SYMBOL_TABLE:
            return struct.unpack_from("<QQ", msg.data, 0)
    raise LayoutError(f"object at {oh_addr} is not a symbol-table group")


# --------------------------------------------------------------------------- datasets
@dataclass
class Dataset:
    name: str
    object_header: int
    shape: tuple[int, ...]
    dtype_class: int
    dtype_size: int
    dtype_signed: bool | None
    dtype_byte_order: str | None
    dtype_precision: int | None
    dtype_offset: int | None
    layout_class: int
    btree_address: int
    chunk_dims: tuple[int, ...]
    filters: list[tuple[int, tuple[int, ...]]] = field(default_factory=list)


def _parse_dataspace(body: bytes) -> tuple[int, ...]:
    version, rank, _flags = struct.unpack_from("<BBB", body, 0)
    if version == 1:
        pos = 8
    elif version == 2:
        pos = 4
    else:
        raise LayoutError(f"unsupported dataspace version {version}")
    return tuple(struct.unpack_from(f"<{rank}Q", body, pos)) if rank else ()


def _parse_filters(body: bytes) -> list[tuple[int, tuple[int, ...]]]:
    version, nfilters = body[0], body[1]
    out = []
    if version == 1:
        pos = 8
    elif version == 2:
        pos = 2
    else:
        raise LayoutError(f"unsupported filter pipeline version {version}")
    for _ in range(nfilters):
        (fid,) = struct.unpack_from("<H", body, pos)
        if version == 1 or fid >= 256:
            name_len, _flags, ncd = struct.unpack_from("<HHH", body, pos + 2)
            pos += 8
            if version == 1:
                pos += name_len  # already padded to a multiple of 8
            else:
                pos += name_len
        else:
            _flags, ncd = struct.unpack_from("<HH", body, pos + 2)
            pos += 6
        cd = struct.unpack_from(f"<{ncd}I", body, pos)
        pos += 4 * ncd
        if version == 1 and ncd % 2:
            pos += 4
        out.append((fid, tuple(cd)))
    return out


def parse_dataset(seg: Segments, name: str, address: int) -> Dataset:
    shape = dtype = layout = None
    filters: list[tuple[int, tuple[int, ...]]] = []
    for msg in read_object_header(seg, address):
        if msg.mtype == MSG_DATASPACE:
            shape = _parse_dataspace(msg.data)
        elif msg.mtype == MSG_DATATYPE:
            dtype = msg.data
        elif msg.mtype == MSG_LAYOUT:
            layout = msg.data
        elif msg.mtype == MSG_FILTER:
            filters = _parse_filters(msg.data)
    if shape is None or dtype is None or layout is None:
        raise LayoutError(f"dataset {name!r} lacks dataspace, datatype or layout")
    dclass = dtype[0] & 0x0F
    bits0 = dtype[1]
    (dsize,) = struct.unpack_from("<I", dtype, 4)
    signed = order = precision = boff = None
    if dclass == 0:
        order = "big" if bits0 & 1 else "little"
        signed = bool(bits0 & 0x08)
        boff, precision = struct.unpack_from("<HH", dtype, 8)
    if layout[0] != 3:
        raise LayoutError(f"dataset {name!r}: data layout version {layout[0]} != 3")
    lclass = layout[1]
    btree = UNDEFINED
    chunk_dims: tuple[int, ...] = ()
    if lclass == 2:
        ndims = layout[2]
        (btree,) = struct.unpack_from("<Q", layout, 3)
        chunk_dims = tuple(struct.unpack_from(f"<{ndims}I", layout, 11))
    return Dataset(name, address, tuple(shape), dclass, dsize, signed, order, precision, boff,
                   lclass, btree, chunk_dims, filters)


@dataclass
class EventFile:
    file_size: int
    root_links: list[str]
    event_links: list[str]
    datasets: dict[str, Dataset]
    ms_to_idx: Dataset


def parse_event_file(seg: Segments) -> EventFile:
    sb = parse_superblock(seg)
    root = group_entries(seg, sb.root_btree, sb.root_heap)
    if sorted(root) != ["events", "ms_to_idx"]:
        raise LayoutError(f"root links {sorted(root)} != ['events', 'ms_to_idx']")
    ev_btree, ev_heap = symbol_table_of(seg, root["events"])
    ev = group_entries(seg, ev_btree, ev_heap)
    if sorted(ev) != ["p", "t", "x", "y"]:
        raise LayoutError(f"events links {sorted(ev)} != ['p', 't', 'x', 'y']")
    datasets = {k: parse_dataset(seg, k, ev[k]) for k in ("x", "y")}
    ms = parse_dataset(seg, "ms_to_idx", root["ms_to_idx"])
    for k, ds in datasets.items():
        check_xy_dataset(ds)
    if datasets["x"].shape != datasets["y"].shape:
        raise LayoutError(f"x shape {datasets['x'].shape} != y shape {datasets['y'].shape}")
    return EventFile(seg.file_size, sorted(root), sorted(ev), datasets, ms)


def check_xy_dataset(ds: Dataset) -> None:
    if len(ds.shape) != 1 or ds.shape[0] < 1:
        raise LayoutError(f"events/{ds.name} shape {ds.shape} is not 1-D")
    if not (ds.dtype_class == 0 and ds.dtype_size == 2 and ds.dtype_signed is False
            and ds.dtype_byte_order == "little" and ds.dtype_precision == 16 and ds.dtype_offset == 0):
        raise LayoutError(f"events/{ds.name} is not little-endian uint16")
    if ds.layout_class != 2:
        raise LayoutError(f"events/{ds.name} layout class {ds.layout_class} is not chunked")
    if ds.chunk_dims != (CHUNK_ELEMS, ELEM_SIZE):
        raise LayoutError(f"events/{ds.name} chunk dims {ds.chunk_dims} != ({CHUNK_ELEMS}, {ELEM_SIZE})")
    if len(ds.filters) != 1 or ds.filters[0][0] != BLOSC_FILTER_ID:
        raise LayoutError(f"events/{ds.name} filters {ds.filters} are not exactly [Blosc 32001]")
    cd = ds.filters[0][1]
    # hdf5plugin Blosc cd_values: [filter rev, blosc version, typesize, chunk bytes, clevel, shuffle, compressor]
    if len(cd) < 7 or cd[2] != ELEM_SIZE or cd[3] != CHUNK_BYTES or cd[5] != 1 or cd[6] != 5:
        raise LayoutError(f"events/{ds.name} Blosc cd_values {cd} != typesize 2, 65536 bytes, byte shuffle, zstd")


# --------------------------------------------------------------------------- chunk B-tree (type 1)
@dataclass(frozen=True)
class ChunkRef:
    index: int  # chunk index = element offset / 32768
    address: int
    size: int
    filter_mask: int


def node_bytes(ndims: int, k: int = 32) -> int:
    key = 8 + 8 * ndims
    return 24 + (2 * k + 1) * key + 2 * k * 8


def chunk_refs(seg: Segments, ds: Dataset, first: int, count: int) -> list[ChunkRef]:
    """Leaf entries for chunk indices [first, first+count), visiting only needed nodes."""
    ndims = len(ds.chunk_dims)
    key_size = 8 + 8 * ndims
    want_lo, want_hi = first * CHUNK_ELEMS, (first + count) * CHUNK_ELEMS
    found: dict[int, ChunkRef] = {}

    def entry_key(raw: bytes, pos: int, final: bool = False) -> tuple[int, int, int]:
        csize, mask = struct.unpack_from("<II", raw, pos)
        offs = struct.unpack_from(f"<{ndims}Q", raw, pos + 8)
        # the closing key of a node is the end bound; libhdf5 writes the element-size dim there
        if offs[-1] not in ((0, ds.chunk_dims[-1]) if final else (0,)):
            raise LayoutError(f"unexpected element-size offset {offs[-1]} in chunk key")
        return csize, mask, offs[0]

    def walk(node: int, depth: int, expect_level: int | None) -> None:
        if depth > 6:
            raise LayoutError("chunk B-tree too deep")
        raw = seg.read(node, node_bytes(ndims))
        if raw[:4] != b"TREE":
            raise LayoutError(f"missing TREE signature at chunk node {node}")
        ntype, level, used = struct.unpack_from("<BBH", raw, 4)
        if ntype != 1:
            raise LayoutError(f"chunk B-tree node type {ntype} != 1")
        if expect_level is not None and level != expect_level:
            raise LayoutError(f"chunk B-tree level {level} != expected {expect_level}")
        if not 1 <= used <= 64:
            raise LayoutError(f"chunk B-tree node at {node} uses {used} entries")
        pos = 24
        keys, children = [], []
        for _ in range(used):
            keys.append(entry_key(raw, pos))
            children.append(struct.unpack_from("<Q", raw, pos + key_size)[0])
            pos += key_size + 8
        keys.append(entry_key(raw, pos, final=True))  # closing (upper bound) key
        lows = [k[2] for k in keys]
        if any(lows[i] >= lows[i + 1] for i in range(used - 1)):
            raise LayoutError(f"chunk B-tree keys not increasing at {node}")
        for i in range(used):
            lo = lows[i]
            hi = lows[i + 1] if i + 1 < used else None
            if level == 0:
                if want_lo <= lo < want_hi:
                    if lo % CHUNK_ELEMS:
                        raise LayoutError(f"chunk offset {lo} not a multiple of {CHUNK_ELEMS}")
                    csize, mask, _ = keys[i]
                    found[lo // CHUNK_ELEMS] = ChunkRef(lo // CHUNK_ELEMS, children[i], csize, mask)
            else:
                upper = hi if hi is not None else keys[used][2] + CHUNK_ELEMS
                if lo < want_hi and upper > want_lo:
                    walk(children[i], depth + 1, level - 1)

    walk(ds.btree_address, 0, None)
    refs = [found.get(first + j) for j in range(count)]
    if any(r is None for r in refs):
        missing = [first + j for j, r in enumerate(refs) if r is None]
        raise LayoutError(f"chunk index lacks entries for chunks {missing[:5]}...")
    for r in refs:
        if r.filter_mask != 0:
            raise LayoutError(f"chunk {r.index} has filter mask {r.filter_mask} (filter skipped)")
        if not 16 <= r.size <= CHUNK_BYTES + 16 + 4 * 64 + 64:
            raise LayoutError(f"chunk {r.index} has implausible stored size {r.size}")
        if r.address + r.size > seg.file_size:
            raise LayoutError(f"chunk {r.index} extends past EOF")
    return refs  # type: ignore[return-value]


# --------------------------------------------------------------------------- window rule
WINDOW_CHUNKS = 128  # 128 x 32,768 = 4,194,304 events


def window_start(n_events: int) -> int:
    """First chunk of the pinned window: centred on the middle chunk of the stream."""
    n_chunks = -(-n_events // CHUNK_ELEMS)
    start = n_chunks // 2 - WINDOW_CHUNKS // 2
    if start < 0 or start + WINDOW_CHUNKS > n_events // CHUNK_ELEMS:
        raise LayoutError(f"stream of {n_events} events too short for a {WINDOW_CHUNKS}-chunk window")
    return start


# --------------------------------------------------------------------------- Blosc1 + zstd
def _zstd_frame_content_size(frame: bytes) -> int | None:
    if frame[:4] != ZSTD_MAGIC:
        raise LayoutError("Blosc block is not a zstd frame")
    fhd = frame[4]
    fcs_flag, single, dict_flag = fhd >> 6, (fhd >> 5) & 1, fhd & 3
    if fhd & 0x08:
        raise LayoutError("zstd frame header reserved bit set")
    pos = 5 + (0 if single else 1) + (0, 1, 2, 4)[dict_flag]
    size = (1 if single else 0, 2, 4, 8)[fcs_flag]
    if size == 0:
        return None
    val = int.from_bytes(frame[pos : pos + size], "little")
    return val + 256 if size == 2 else val


def zstd_decompress(frames: bytes) -> bytes:
    proc = subprocess.run(["zstd", "-q", "-d", "-c", "--no-progress"], input=frames,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise LayoutError(f"zstd failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def _unshuffle(block: bytes, typesize: int) -> bytes:
    n = len(block) // typesize
    body = block[: n * typesize]
    out = bytearray(len(block))
    for i in range(typesize):
        out[i : n * typesize : typesize] = body[i * n : (i + 1) * n]
    out[n * typesize :] = block[n * typesize :]
    return bytes(out)


def blosc_decode(buf: bytes, expect_nbytes: int = CHUNK_BYTES, expect_typesize: int = ELEM_SIZE) -> bytes:
    """Decode one Blosc1 buffer (as written by c-blosc 1.x, ZSTD codec)."""
    if len(buf) < 16:
        raise LayoutError("Blosc buffer shorter than its header")
    version, _vlz, flags, typesize, nbytes, blocksize, cbytes = struct.unpack_from("<BBBBIII", buf, 0)
    if version not in (1, 2):
        raise LayoutError(f"unsupported Blosc format version {version}")
    if cbytes != len(buf):
        raise LayoutError(f"Blosc cbytes {cbytes} != stored chunk size {len(buf)}")
    if typesize != expect_typesize or nbytes != expect_nbytes:
        raise LayoutError(f"Blosc typesize/nbytes {typesize}/{nbytes} != {expect_typesize}/{expect_nbytes}")
    if blocksize <= 0 or blocksize > nbytes or blocksize % typesize:
        raise LayoutError(f"bad Blosc blocksize {blocksize}")
    if flags & 0x04:
        raise LayoutError("Blosc bit-shuffle is not expected")
    byte_shuffle = bool(flags & 0x01)
    if flags & 0x02:  # memcpyed: whole buffer stored raw after the header
        raw = buf[16:]
        if len(raw) != nbytes:
            raise LayoutError("memcpyed Blosc buffer size mismatch")
        return raw  # memcpyed buffers are never shuffled
    codec = flags >> 5
    if codec != 4:
        raise LayoutError(f"Blosc compressor code {codec} is not ZSTD (4)")
    nblocks = -(-nbytes // blocksize)
    bstarts = struct.unpack_from(f"<{nblocks}i", buf, 16)
    dont_split = bool(flags & 0x10)
    out = bytearray()
    for b in range(nblocks):
        bsize = blocksize if (b + 1) * blocksize <= nbytes else nbytes - b * blocksize
        nsplits = 1 if (dont_split or typesize == 1) else typesize
        if bsize % nsplits:
            nsplits = 1
        neblock = bsize // nsplits
        pos = bstarts[b]
        if not 16 + 4 * nblocks <= pos < len(buf):
            raise LayoutError(f"Blosc bstart {pos} out of range")
        block = bytearray()
        for _ in range(nsplits):
            (csize,) = struct.unpack_from("<i", buf, pos)
            pos += 4
            if csize <= 0 or pos + csize > len(buf):
                raise LayoutError(f"bad Blosc stream size {csize}")
            stream = buf[pos : pos + csize]
            pos += csize
            if csize == neblock:  # stored uncompressed
                block += stream
                continue
            fcs = _zstd_frame_content_size(stream)
            if fcs is not None and fcs != neblock:
                raise LayoutError(f"zstd frame content size {fcs} != {neblock}")
            dec = zstd_decompress(stream)
            if len(dec) != neblock:
                raise LayoutError(f"zstd stream decoded to {len(dec)} bytes, expected {neblock}")
            block += dec
        out += _unshuffle(bytes(block), typesize) if (byte_shuffle and typesize > 1) else block
    if len(out) != nbytes:
        raise LayoutError(f"Blosc decoded {len(out)} bytes != nbytes {nbytes}")
    return bytes(out)


def u16_stats(raw: bytes) -> tuple[int, int, int]:
    """(min, max, count) of little-endian uint16 values."""
    if len(raw) % 2:
        raise LayoutError("odd byte count for uint16 data")
    vals = memoryview(raw).cast("H")  # host order; checked little-endian below
    return min(vals), max(vals), len(vals)


if struct.pack("=H", 1) != struct.pack("<H", 1):  # pragma: no cover - documented assumption
    raise SystemExit("this helper assumes a little-endian host")
