#!/usr/bin/env python3
"""Minimal pure-stdlib 7z reader for single-coder LZMA1/LZMA2 solid archives.

Scope (deliberately narrow, everything else is rejected):
- 7z signature header v0.x with a plain or LZMA-encoded (kEncodedHeader) header
- folders with exactly one coder that is LZMA1 (03 01 01) or LZMA2 (21),
  one packed stream and one unpacked stream, no bind pairs, no filters
- SubStreamsInfo sizes and CRC32 digests, FilesInfo names and empty-stream bits

The archive is read through a ``read(offset, size)`` callable so the same code
works on a full local file or on sparse probe fragments.
"""
from __future__ import annotations

import lzma
import struct
import zlib
from dataclasses import dataclass, field
from typing import Callable, Iterator

SIGNATURE = b"7z\xbc\xaf\x27\x1c"
K_END = 0x00
K_HEADER = 0x01
K_ARCHIVE_PROPERTIES = 0x02
K_ADDITIONAL_STREAMS_INFO = 0x03
K_MAIN_STREAMS_INFO = 0x04
K_FILES_INFO = 0x05
K_PACK_INFO = 0x06
K_UNPACK_INFO = 0x07
K_SUBSTREAMS_INFO = 0x08
K_SIZE = 0x09
K_CRC = 0x0A
K_FOLDER = 0x0B
K_CODERS_UNPACK_SIZE = 0x0C
K_NUM_UNPACK_STREAM = 0x0D
K_EMPTY_STREAM = 0x0E
K_EMPTY_FILE = 0x0F
K_NAME = 0x11
K_ENCODED_HEADER = 0x17
K_DUMMY = 0x19

LZMA1_ID = b"\x03\x01\x01"
LZMA2_ID = b"\x21"


class SevenZipError(ValueError):
    pass


class Cursor:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def byte(self) -> int:
        if self.pos >= len(self.data):
            raise SevenZipError("header truncated")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def take(self, size: int) -> bytes:
        if size < 0 or self.pos + size > len(self.data):
            raise SevenZipError("header truncated")
        chunk = self.data[self.pos : self.pos + size]
        self.pos += size
        return chunk

    def number(self) -> int:
        first = self.byte()
        mask = 0x80
        value = 0
        for index in range(8):
            if first & mask == 0:
                return value | ((first & (mask - 1)) << (8 * index))
            value |= self.byte() << (8 * index)
            mask >>= 1
        return value

    def uint32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def bits(self, count: int) -> list[bool]:
        out: list[bool] = []
        mask = 0
        current = 0
        for _ in range(count):
            if mask == 0:
                current = self.byte()
                mask = 0x80
            out.append(bool(current & mask))
            mask >>= 1
        return out

    def expect(self, value: int, what: str) -> None:
        got = self.byte()
        if got != value:
            raise SevenZipError(f"expected {what} (0x{value:02x}), got 0x{got:02x} at {self.pos - 1}")


@dataclass
class Coder:
    method: bytes
    props: bytes


@dataclass
class Folder:
    coder: Coder
    unpack_size: int = 0
    crc: int | None = None
    num_substreams: int = 1
    substream_sizes: list[int] = field(default_factory=list)
    substream_crcs: list[int | None] = field(default_factory=list)


@dataclass
class StreamsInfo:
    pack_pos: int = 0
    pack_sizes: list[int] = field(default_factory=list)
    folders: list[Folder] = field(default_factory=list)


@dataclass
class Entry:
    name: str
    has_stream: bool
    size: int = 0
    crc: int | None = None
    folder: int = -1
    offset_in_folder: int = 0


def read_digests(cur: Cursor, count: int) -> list[int | None]:
    all_defined = cur.byte()
    defined = [True] * count if all_defined else cur.bits(count)
    return [cur.uint32() if flag else None for flag in defined]


def read_pack_info(cur: Cursor, info: StreamsInfo) -> None:
    info.pack_pos = cur.number()
    count = cur.number()
    while True:
        prop = cur.byte()
        if prop == K_END:
            break
        if prop == K_SIZE:
            info.pack_sizes = [cur.number() for _ in range(count)]
        elif prop == K_CRC:
            read_digests(cur, count)
        else:
            raise SevenZipError(f"unexpected PackInfo property 0x{prop:02x}")
    if len(info.pack_sizes) != count:
        raise SevenZipError("PackInfo lacks sizes")


def read_folder(cur: Cursor) -> Folder:
    num_coders = cur.number()
    if num_coders != 1:
        raise SevenZipError(f"unsupported folder with {num_coders} coders")
    flags = cur.byte()
    id_size = flags & 0x0F
    if flags & 0x10:
        raise SevenZipError("complex coders are not supported")
    if flags & 0x80:
        raise SevenZipError("alternative coder methods are not supported")
    method = cur.take(id_size)
    props = cur.take(cur.number()) if flags & 0x20 else b""
    if method not in (LZMA1_ID, LZMA2_ID):
        raise SevenZipError(f"unsupported coder method {method.hex()}")
    return Folder(Coder(method, props))


def read_unpack_info(cur: Cursor, info: StreamsInfo) -> None:
    cur.expect(K_FOLDER, "kFolder")
    count = cur.number()
    if cur.byte() != 0:
        raise SevenZipError("external folder definitions are not supported")
    info.folders = [read_folder(cur) for _ in range(count)]
    cur.expect(K_CODERS_UNPACK_SIZE, "kCodersUnpackSize")
    for folder in info.folders:
        folder.unpack_size = cur.number()
    while True:
        prop = cur.byte()
        if prop == K_END:
            break
        if prop == K_CRC:
            for folder, crc in zip(info.folders, read_digests(cur, count)):
                folder.crc = crc
        else:
            raise SevenZipError(f"unexpected UnpackInfo property 0x{prop:02x}")


def read_substreams_info(cur: Cursor, info: StreamsInfo) -> None:
    prop = cur.byte()
    if prop == K_NUM_UNPACK_STREAM:
        for folder in info.folders:
            folder.num_substreams = cur.number()
        prop = cur.byte()
    if prop == K_SIZE:
        for folder in info.folders:
            if folder.num_substreams == 0:
                continue
            sizes = [cur.number() for _ in range(folder.num_substreams - 1)]
            remainder = folder.unpack_size - sum(sizes)
            if remainder < 0:
                raise SevenZipError("substream sizes exceed folder size")
            folder.substream_sizes = sizes + [remainder]
        prop = cur.byte()
    else:
        for folder in info.folders:
            if folder.num_substreams == 1:
                folder.substream_sizes = [folder.unpack_size]
            elif folder.num_substreams > 1:
                raise SevenZipError("multiple substreams without kSize")
    for folder in info.folders:
        folder.substream_crcs = [None] * folder.num_substreams
        if folder.num_substreams == 1 and folder.crc is not None:
            folder.substream_crcs = [folder.crc]
    while prop != K_END:
        if prop == K_CRC:
            pending = [
                (fi, si)
                for fi, folder in enumerate(info.folders)
                for si in range(folder.num_substreams)
                if not (folder.num_substreams == 1 and folder.crc is not None)
            ]
            for (fi, si), crc in zip(pending, read_digests(cur, len(pending))):
                info.folders[fi].substream_crcs[si] = crc
        else:
            raise SevenZipError(f"unexpected SubStreamsInfo property 0x{prop:02x}")
        prop = cur.byte()


def read_streams_info(cur: Cursor) -> StreamsInfo:
    info = StreamsInfo()
    while True:
        prop = cur.byte()
        if prop == K_END:
            break
        if prop == K_PACK_INFO:
            read_pack_info(cur, info)
        elif prop == K_UNPACK_INFO:
            read_unpack_info(cur, info)
        elif prop == K_SUBSTREAMS_INFO:
            read_substreams_info(cur, info)
        else:
            raise SevenZipError(f"unexpected StreamsInfo property 0x{prop:02x}")
    if len(info.pack_sizes) != len(info.folders):
        raise SevenZipError("only one packed stream per folder is supported")
    for folder in info.folders:
        if not folder.substream_sizes and folder.num_substreams:
            folder.substream_sizes = [folder.unpack_size]
            folder.substream_crcs = [folder.crc]
    return info


def read_files_info(cur: Cursor) -> tuple[list[str], list[bool]]:
    count = cur.number()
    names: list[str] = []
    empty_stream = [False] * count
    while True:
        prop = cur.byte()
        if prop == K_END:
            break
        size = cur.number()
        payload = cur.take(size)
        if prop == K_NAME:
            if not payload or payload[0] != 0:
                raise SevenZipError("external file names are not supported")
            raw = payload[1:]
            if len(raw) % 2:
                raise SevenZipError("odd-length UTF-16 name table")
            text = raw.decode("utf-16-le")
            if not text.endswith("\x00"):
                raise SevenZipError("unterminated name table")
            names = text[:-1].split("\x00")
        elif prop == K_EMPTY_STREAM:
            empty_stream = Cursor(payload).bits(count)
    if len(names) != count:
        raise SevenZipError(f"name count {len(names)} != file count {count}")
    return names, empty_stream


def lzma_filters(coder: Coder) -> list[dict]:
    if coder.method == LZMA1_ID:
        if len(coder.props) != 5:
            raise SevenZipError("LZMA1 properties must be 5 bytes")
        d = coder.props[0]
        if d >= 9 * 5 * 5:
            raise SevenZipError("invalid LZMA1 lc/lp/pb byte")
        lc = d % 9
        lp = (d // 9) % 5
        pb = d // 45
        dict_size = struct.unpack("<I", coder.props[1:5])[0]
        return [{"id": lzma.FILTER_LZMA1, "dict_size": dict_size, "lc": lc, "lp": lp, "pb": pb}]
    if len(coder.props) != 1 or coder.props[0] > 40:
        raise SevenZipError("invalid LZMA2 property byte")
    bits = coder.props[0]
    dict_size = 0xFFFFFFFF if bits == 40 else (2 | (bits & 1)) << (bits // 2 + 11)
    return [{"id": lzma.FILTER_LZMA2, "dict_size": dict_size}]


Reader = Callable[[int, int], bytes]


def decode_folder_stream(
    read: Reader, offset: int, packed_size: int, folder: Folder, chunk: int = 1 << 20
) -> Iterator[bytes]:
    """Yield the unpacked bytes of one folder, exactly ``folder.unpack_size``."""
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=lzma_filters(folder.coder))
    produced = 0
    consumed = 0
    while consumed < packed_size:
        size = min(chunk, packed_size - consumed)
        data = read(offset + consumed, size)
        if len(data) != size:
            raise SevenZipError("packed stream truncated")
        consumed += size
        out = decoder.decompress(data)
        if out:
            if produced + len(out) > folder.unpack_size:
                out = out[: folder.unpack_size - produced]
            produced += len(out)
            yield out
        if produced >= folder.unpack_size:
            break
    if produced != folder.unpack_size:
        raise SevenZipError(f"folder decoded to {produced} bytes, expected {folder.unpack_size}")


@dataclass
class Archive:
    archive_size: int
    header_offset: int
    streams: StreamsInfo
    entries: list[Entry]

    def folder_offset(self, index: int) -> int:
        return 32 + self.streams.pack_pos + sum(self.streams.pack_sizes[:index])


def parse_start_header(raw: bytes) -> tuple[int, int, int]:
    if len(raw) < 32 or raw[:6] != SIGNATURE:
        raise SevenZipError("not a 7z archive")
    if raw[6] != 0:
        raise SevenZipError(f"unsupported 7z major version {raw[6]}")
    start_crc = struct.unpack_from("<I", raw, 8)[0]
    if zlib.crc32(raw[12:32]) != start_crc:
        raise SevenZipError("start header CRC mismatch")
    offset, size, crc = struct.unpack_from("<QQI", raw, 12)
    return offset, size, crc


def open_archive(read: Reader, archive_size: int) -> Archive:
    offset, size, crc = parse_start_header(read(0, 32))
    header_offset = 32 + offset
    if header_offset + size != archive_size:
        raise SevenZipError("next header does not end at the archive end")
    raw = read(header_offset, size)
    if zlib.crc32(raw) != crc:
        raise SevenZipError("next header CRC mismatch")
    cur = Cursor(raw)
    kind = cur.byte()
    if kind == K_ENCODED_HEADER:
        enc = read_streams_info(cur)
        if len(enc.folders) != 1:
            raise SevenZipError("encoded header must use one folder")
        folder = enc.folders[0]
        start = 32 + enc.pack_pos
        raw = b"".join(decode_folder_stream(read, start, enc.pack_sizes[0], folder))
        if folder.crc is not None and zlib.crc32(raw) != folder.crc:
            raise SevenZipError("decoded header CRC mismatch")
        cur = Cursor(raw)
        kind = cur.byte()
    if kind != K_HEADER:
        raise SevenZipError(f"expected kHeader, got 0x{kind:02x}")
    streams = StreamsInfo()
    names: list[str] = []
    empty: list[bool] = []
    while True:
        prop = cur.byte()
        if prop == K_END:
            break
        if prop == K_MAIN_STREAMS_INFO:
            streams = read_streams_info(cur)
        elif prop == K_FILES_INFO:
            names, empty = read_files_info(cur)
        elif prop in (K_ARCHIVE_PROPERTIES, K_ADDITIONAL_STREAMS_INFO):
            raise SevenZipError("archive properties / additional streams are not supported")
        else:
            raise SevenZipError(f"unexpected header property 0x{prop:02x}")
    substreams = [
        (fi, size, crc)
        for fi, folder in enumerate(streams.folders)
        for size, crc in zip(folder.substream_sizes, folder.substream_crcs)
    ]
    entries: list[Entry] = []
    position = 0
    offsets: dict[int, int] = {}
    for name, is_empty in zip(names, empty):
        if is_empty:
            entries.append(Entry(name=name, has_stream=False))
            continue
        if position >= len(substreams):
            raise SevenZipError("more non-empty files than substreams")
        fi, size, crc = substreams[position]
        position += 1
        entries.append(
            Entry(name=name, has_stream=True, size=size, crc=crc, folder=fi, offset_in_folder=offsets.get(fi, 0))
        )
        offsets[fi] = offsets.get(fi, 0) + size
    if position != len(substreams):
        raise SevenZipError("substream count does not match non-empty files")
    return Archive(archive_size=archive_size, header_offset=header_offset, streams=streams, entries=entries)


def iter_members(read: Reader, archive: Archive) -> Iterator[tuple[Entry, bytes]]:
    """Decode every folder once and yield (entry, content) in archive order.

    Each member's CRC32 is verified before it is yielded. Only one member's
    bytes are held in memory at a time.
    """
    by_folder: dict[int, list[Entry]] = {}
    for entry in archive.entries:
        if entry.has_stream:
            by_folder.setdefault(entry.folder, []).append(entry)
    for fi, folder in enumerate(archive.streams.folders):
        members = by_folder.get(fi, [])
        stream = decode_folder_stream(read, archive.folder_offset(fi), archive.streams.pack_sizes[fi], folder)
        buffer = bytearray()
        for entry in members:
            while len(buffer) < entry.size:
                try:
                    buffer += next(stream)
                except StopIteration:
                    raise SevenZipError(f"folder ended before member {entry.name}") from None
            content = bytes(buffer[: entry.size])
            del buffer[: entry.size]
            if entry.crc is not None and zlib.crc32(content) != entry.crc:
                raise SevenZipError(f"CRC32 mismatch for {entry.name}")
            yield entry, content
        for rest in stream:
            buffer += rest
        if buffer:
            raise SevenZipError(f"folder {fi} has {len(buffer)} trailing bytes")


def file_reader(path: str) -> tuple[Reader, int]:
    handle = open(path, "rb")
    handle.seek(0, 2)
    size = handle.tell()

    def read(offset: int, length: int) -> bytes:
        handle.seek(offset)
        return handle.read(length)

    return read, size
