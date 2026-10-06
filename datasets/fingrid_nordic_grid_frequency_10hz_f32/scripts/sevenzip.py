#!/usr/bin/env python3
"""Minimal pure-stdlib reader for single-folder LZMA/LZMA2 7z archives.

Supports exactly what the Fingrid monthly frequency archives use:

- the 32-byte signature/start header (with its CRC32 check),
- a plain (0x01) or LZMA-encoded (0x17) next header,
- one solid folder with one LZMA (03 01 01) or LZMA2 (21) coder and one pack
  stream, split into named substreams with per-file CRC32 digests,
- optional directory entries (empty stream, not an empty file), which carry
  no data and are listed separately.

Anything else (multiple folders, filters such as BCJ, encryption, external
data, zero-length files) raises SevenZipError instead of guessing.
"""
from __future__ import annotations

import lzma
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterator

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

CODEC_LZMA = b"\x03\x01\x01"
CODEC_LZMA2 = b"\x21"


class SevenZipError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def byte(self) -> int:
        if self.pos >= len(self.data):
            raise SevenZipError("truncated 7z header")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise SevenZipError("truncated 7z header")
        value = self.data[self.pos : self.pos + count]
        self.pos += count
        return value

    def number(self) -> int:
        first = self.byte()
        mask = 0x80
        value = 0
        for index in range(8):
            if first & mask == 0:
                high = first & (mask - 1)
                return value | (high << (8 * index))
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

    def digests(self, count: int) -> list[int | None]:
        all_defined = self.byte()
        defined = [True] * count if all_defined else self.bits(count)
        return [self.uint32() if flag else None for flag in defined]


@dataclass
class Coder:
    codec_id: bytes
    num_in: int
    num_out: int
    properties: bytes


@dataclass
class Folder:
    coders: list[Coder]
    bind_pairs: list[tuple[int, int]]
    packed_indices: list[int]
    unpack_sizes: list[int] = field(default_factory=list)
    crc: int | None = None


@dataclass
class StreamsInfo:
    pack_pos: int = 0
    pack_sizes: list[int] = field(default_factory=list)
    folders: list[Folder] = field(default_factory=list)
    substream_counts: list[int] = field(default_factory=list)
    substream_sizes: list[int] = field(default_factory=list)
    substream_crcs: list[int | None] = field(default_factory=list)


@dataclass
class Entry:
    name: str
    size: int
    crc32: int | None


@dataclass
class Archive:
    path: Path
    version: tuple[int, int]
    next_header_offset: int
    next_header_size: int
    header_encoded: bool
    header_coder: str
    pack_pos: int
    pack_size: int
    coder: Coder
    folder_unpack_size: int
    entries: list[Entry]
    directories: list[str]

    @property
    def coder_name(self) -> str:
        return "LZMA2" if self.coder.codec_id == CODEC_LZMA2 else "LZMA"

    def iter_members(self, chunk_size: int = 4 * 1024 * 1024) -> Iterator[tuple[Entry, bytes]]:
        """Stream-decode the solid folder and yield (entry, bytes) per member.

        Each member's CRC32 is checked against the header digest and the
        folder must end exactly at the declared unpack size.
        """
        decompressor = _make_decompressor(self.coder)
        with self.path.open("rb") as handle:
            handle.seek(32 + self.pack_pos)
            remaining_pack = self.pack_size
            pending = bytearray()
            produced = 0
            entry_index = 0

            def drain() -> Iterator[tuple[Entry, bytes]]:
                nonlocal entry_index
                while entry_index < len(self.entries) and len(pending) >= self.entries[entry_index].size:
                    entry = self.entries[entry_index]
                    payload = bytes(pending[: entry.size])
                    del pending[: entry.size]
                    actual = zlib.crc32(payload) & 0xFFFFFFFF
                    if entry.crc32 is not None and actual != entry.crc32:
                        raise SevenZipError(
                            f"CRC32 mismatch for {entry.name}: header={entry.crc32:08x} actual={actual:08x}"
                        )
                    entry_index += 1
                    yield entry, payload

            while not decompressor.eof:
                if decompressor.needs_input:
                    if remaining_pack == 0:
                        break
                    block = handle.read(min(chunk_size, remaining_pack))
                    if not block:
                        raise SevenZipError("archive truncated inside pack stream")
                    remaining_pack -= len(block)
                else:
                    block = b""
                limit = self.folder_unpack_size - produced
                if limit <= 0:
                    if self.coder.codec_id == CODEC_LZMA:
                        break  # LZMA1 streams in 7z usually carry no end marker
                    # LZMA2: the next control byte must be the end marker.
                    out = decompressor.decompress(block, max_length=1)
                    if out:
                        raise SevenZipError("decoded data exceeds the declared folder unpack size")
                    continue
                out = decompressor.decompress(block, max_length=min(limit, 64 * 1024 * 1024))
                produced += len(out)
                pending += out
                yield from drain()
            if self.coder.codec_id == CODEC_LZMA:
                # The range coder's 5-byte flush may be left unread when the last
                # symbol completes early; anything longer means a size mismatch.
                if remaining_pack > 16:
                    raise SevenZipError(f"{remaining_pack} pack bytes left after the LZMA folder ended")
            elif remaining_pack != 0 or decompressor.unused_data:
                raise SevenZipError("pack stream has trailing bytes after the LZMA2 end marker")
            if produced != self.folder_unpack_size:
                raise SevenZipError(
                    f"folder decoded to {produced} bytes, header declares {self.folder_unpack_size}"
                )
            if self.coder.codec_id == CODEC_LZMA2 and not decompressor.eof:
                raise SevenZipError("LZMA2 stream lacks its end marker")
            if entry_index != len(self.entries) or pending:
                raise SevenZipError("substream sizes do not tile the decoded folder")


def _lzma1_filter(props: bytes) -> dict:
    if len(props) != 5:
        raise SevenZipError(f"LZMA properties must be 5 bytes, got {len(props)}")
    d = props[0]
    if d >= 9 * 5 * 5:
        raise SevenZipError("invalid LZMA lc/lp/pb byte")
    lc = d % 9
    d //= 9
    lp = d % 5
    pb = d // 5
    dict_size = struct.unpack("<I", props[1:5])[0]
    return {"id": lzma.FILTER_LZMA1, "lc": lc, "lp": lp, "pb": pb, "dict_size": max(dict_size, 4096)}


def _lzma2_filter(props: bytes) -> dict:
    if len(props) != 1 or props[0] > 40:
        raise SevenZipError(f"invalid LZMA2 properties {props.hex()}")
    p = props[0]
    dict_size = 0xFFFFFFFF if p == 40 else (2 | (p & 1)) << (p // 2 + 11)
    return {"id": lzma.FILTER_LZMA2, "dict_size": dict_size}


def _make_decompressor(coder: Coder) -> lzma.LZMADecompressor:
    if coder.codec_id == CODEC_LZMA2:
        flt = _lzma2_filter(coder.properties)
    elif coder.codec_id == CODEC_LZMA:
        flt = _lzma1_filter(coder.properties)
    else:
        raise SevenZipError(f"unsupported 7z codec {coder.codec_id.hex()}")
    return lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[flt])


def _read_folder(r: _Reader) -> Folder:
    num_coders = r.number()
    if not 1 <= num_coders <= 4:
        raise SevenZipError(f"unexpected coder count {num_coders}")
    coders: list[Coder] = []
    total_in = total_out = 0
    for _ in range(num_coders):
        flags = r.byte()
        if flags & 0x80:
            raise SevenZipError("alternative coder methods are not supported")
        codec_id = r.take(flags & 0x0F)
        if flags & 0x10:
            num_in, num_out = r.number(), r.number()
        else:
            num_in = num_out = 1
        properties = r.take(r.number()) if flags & 0x20 else b""
        coders.append(Coder(codec_id, num_in, num_out, properties))
        total_in += num_in
        total_out += num_out
    bind_pairs = [(r.number(), r.number()) for _ in range(total_out - 1)]
    num_packed = total_in - len(bind_pairs)
    packed = [r.number() for _ in range(num_packed)] if num_packed > 1 else [0]
    return Folder(coders, bind_pairs, packed)


def _read_streams_info(r: _Reader) -> StreamsInfo:
    info = StreamsInfo()
    nid = r.byte()
    if nid == K_PACK_INFO:
        info.pack_pos = r.number()
        num_pack = r.number()
        nid = r.byte()
        if nid == K_SIZE:
            info.pack_sizes = [r.number() for _ in range(num_pack)]
            nid = r.byte()
        if nid == K_CRC:
            r.digests(num_pack)
            nid = r.byte()
        if nid != K_END:
            raise SevenZipError(f"unexpected property {nid:#x} in PackInfo")
        nid = r.byte()
    if nid == K_UNPACK_INFO:
        if r.byte() != K_FOLDER:
            raise SevenZipError("UnpackInfo lacks kFolder")
        num_folders = r.number()
        if r.byte() != 0:
            raise SevenZipError("external folder data is not supported")
        info.folders = [_read_folder(r) for _ in range(num_folders)]
        if r.byte() != K_CODERS_UNPACK_SIZE:
            raise SevenZipError("UnpackInfo lacks kCodersUnpackSize")
        for folder in info.folders:
            folder.unpack_sizes = [r.number() for coder in folder.coders for _ in range(coder.num_out)]
        nid = r.byte()
        if nid == K_CRC:
            for folder, crc in zip(info.folders, r.digests(num_folders)):
                folder.crc = crc
            nid = r.byte()
        if nid != K_END:
            raise SevenZipError(f"unexpected property {nid:#x} in UnpackInfo")
        nid = r.byte()
    if nid == K_SUBSTREAMS_INFO:
        counts = [1] * len(info.folders)
        nid = r.byte()
        if nid == K_NUM_UNPACK_STREAM:
            counts = [r.number() for _ in info.folders]
            nid = r.byte()
        sizes: list[int] = []
        have_sizes = nid == K_SIZE
        for folder, count in zip(info.folders, counts):
            if count == 0:
                continue
            total = folder.unpack_sizes[-1] if folder.unpack_sizes else 0
            used = 0
            for _ in range(count - 1):
                if not have_sizes:
                    raise SevenZipError("multi-stream folder lacks substream sizes")
                size = r.number()
                sizes.append(size)
                used += size
            if used > total:
                raise SevenZipError("substream sizes exceed folder unpack size")
            sizes.append(total - used)
        if have_sizes:
            nid = r.byte()
        crcs: list[int | None] = []
        unknown = sum(
            count for folder, count in zip(info.folders, counts) if not (count == 1 and folder.crc is not None)
        )
        digests: list[int | None] = []
        if nid == K_CRC:
            digests = r.digests(unknown)
            nid = r.byte()
        position = 0
        for folder, count in zip(info.folders, counts):
            if count == 1 and folder.crc is not None:
                crcs.append(folder.crc)
            else:
                for _ in range(count):
                    crcs.append(digests[position] if position < len(digests) else None)
                    position += 1
        if nid != K_END:
            raise SevenZipError(f"unexpected property {nid:#x} in SubStreamsInfo")
        info.substream_counts = counts
        info.substream_sizes = sizes
        info.substream_crcs = crcs
        nid = r.byte()
    elif info.folders:
        info.substream_counts = [1] * len(info.folders)
        info.substream_sizes = [folder.unpack_sizes[-1] for folder in info.folders]
        info.substream_crcs = [folder.crc for folder in info.folders]
    if nid != K_END:
        raise SevenZipError(f"unexpected property {nid:#x} at end of StreamsInfo")
    return info


def _read_files_info(r: _Reader) -> tuple[list[str], list[bool], list[bool]]:
    num_files = r.number()
    names: list[str] = []
    empty_stream = [False] * num_files
    empty_file: list[bool] = []
    while True:
        prop = r.byte()
        if prop == K_END:
            break
        size = r.number()
        body = _Reader(r.take(size))
        if prop == K_NAME:
            if body.byte() != 0:
                raise SevenZipError("external file names are not supported")
            raw = body.data[body.pos :]
            text = raw.decode("utf-16-le")
            if not text.endswith("\x00"):
                raise SevenZipError("file-name block is not NUL terminated")
            names = text[:-1].split("\x00")
        elif prop == K_EMPTY_STREAM:
            empty_stream = body.bits(num_files)
        elif prop == K_EMPTY_FILE:
            empty_file = body.bits(sum(empty_stream))
        # Times, attributes, kDummy and other properties are not needed.
    if len(names) != num_files:
        raise SevenZipError(f"expected {num_files} names, found {len(names)}")
    # Expand kEmptyFile (indexed over empty-stream entries) to all entries.
    is_empty_file = [False] * num_files
    position = 0
    for index, flag in enumerate(empty_stream):
        if flag:
            is_empty_file[index] = position < len(empty_file) and empty_file[position]
            position += 1
    return names, empty_stream, is_empty_file


def _decode_encoded_header(handle: BinaryIO, info: StreamsInfo) -> bytes:
    if len(info.folders) != 1 or len(info.pack_sizes) != 1:
        raise SevenZipError("encoded header must use one folder and one pack stream")
    folder = info.folders[0]
    if len(folder.coders) != 1:
        raise SevenZipError("encoded header uses a filter chain")
    handle.seek(32 + info.pack_pos)
    packed = handle.read(info.pack_sizes[0])
    if len(packed) != info.pack_sizes[0]:
        raise SevenZipError("archive truncated inside encoded header")
    decompressor = _make_decompressor(folder.coders[0])
    size = folder.unpack_sizes[-1]
    header = decompressor.decompress(packed, max_length=size)
    if len(header) != size:
        raise SevenZipError(f"encoded header decoded to {len(header)} bytes, expected {size}")
    if folder.crc is not None and zlib.crc32(header) & 0xFFFFFFFF != folder.crc:
        raise SevenZipError("encoded header CRC32 mismatch")
    return header


def open_archive(path: Path) -> Archive:
    path = Path(path)
    file_size = path.stat().st_size
    with path.open("rb") as handle:
        start = handle.read(32)
        if len(start) != 32 or start[:6] != SIGNATURE:
            raise SevenZipError("missing 7z signature")
        major, minor = start[6], start[7]
        if major != 0:
            raise SevenZipError(f"unsupported 7z major version {major}")
        start_crc = struct.unpack("<I", start[8:12])[0]
        if zlib.crc32(start[12:32]) & 0xFFFFFFFF != start_crc:
            raise SevenZipError("start-header CRC32 mismatch")
        next_offset, next_size, next_crc = struct.unpack("<QQI", start[12:32])
        if 32 + next_offset + next_size != file_size:
            raise SevenZipError(
                f"next header does not end at EOF: 32+{next_offset}+{next_size} != {file_size}"
            )
        handle.seek(32 + next_offset)
        header = handle.read(next_size)
        if zlib.crc32(header) & 0xFFFFFFFF != next_crc:
            raise SevenZipError("next-header CRC32 mismatch")
        encoded = False
        header_coder = "none"
        r = _Reader(header)
        nid = r.byte()
        if nid == K_ENCODED_HEADER:
            encoded = True
            enc_info = _read_streams_info(r)
            header_coder = enc_info.folders[0].coders[0].codec_id.hex() if enc_info.folders else "?"
            header = _decode_encoded_header(handle, enc_info)
            r = _Reader(header)
            nid = r.byte()
        if nid != K_HEADER:
            raise SevenZipError(f"unexpected top-level header id {nid:#x}")
        nid = r.byte()
        if nid == K_ARCHIVE_PROPERTIES:
            while True:
                prop = r.byte()
                if prop == K_END:
                    break
                r.take(r.number())
            nid = r.byte()
        if nid == K_ADDITIONAL_STREAMS_INFO:
            raise SevenZipError("additional streams are not supported")
        if nid != K_MAIN_STREAMS_INFO:
            raise SevenZipError("archive has no main streams")
        info = _read_streams_info(r)
        nid = r.byte()
        if nid != K_FILES_INFO:
            raise SevenZipError("archive has no FilesInfo")
        names, empty_stream, empty_file = _read_files_info(r)
        if r.byte() != K_END:
            raise SevenZipError("header does not end with kEnd")
    if len(info.folders) != 1 or len(info.pack_sizes) != 1:
        raise SevenZipError("expected exactly one solid folder and one pack stream")
    folder = info.folders[0]
    if len(folder.coders) != 1 or folder.coders[0].num_in != 1 or folder.coders[0].num_out != 1:
        raise SevenZipError("expected a single-coder folder (no filter chain)")
    if folder.coders[0].codec_id not in (CODEC_LZMA, CODEC_LZMA2):
        raise SevenZipError(f"unsupported main codec {folder.coders[0].codec_id.hex()}")
    if any(empty_file):
        raise SevenZipError("zero-length file entries are not expected")
    directories = [name for name, empty in zip(names, empty_stream) if empty]
    stream_names = [name for name, empty in zip(names, empty_stream) if not empty]
    if len(stream_names) != len(info.substream_sizes):
        raise SevenZipError(f"{len(stream_names)} stream names but {len(info.substream_sizes)} substreams")
    if 32 + info.pack_pos + info.pack_sizes[0] > 32 + next_offset:
        raise SevenZipError("pack stream overlaps the next header")
    entries = [
        Entry(name, size, crc) for name, size, crc in zip(stream_names, info.substream_sizes, info.substream_crcs)
    ]
    return Archive(
        path=path,
        version=(major, minor),
        next_header_offset=next_offset,
        next_header_size=next_size,
        header_encoded=encoded,
        header_coder=header_coder,
        pack_pos=info.pack_pos,
        pack_size=info.pack_sizes[0],
        coder=folder.coders[0],
        folder_unpack_size=folder.unpack_sizes[-1],
        entries=entries,
        directories=directories,
    )


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="List a 7z archive using the pure-stdlib reader")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--extract-to", type=Path, help="decode every member into this directory")
    args = parser.parse_args()
    archive = open_archive(args.archive)
    print(
        json.dumps(
            {
                "version": archive.version,
                "header_encoded": archive.header_encoded,
                "coder": archive.coder_name,
                "coder_properties": archive.coder.properties.hex(),
                "pack_pos": archive.pack_pos,
                "pack_size": archive.pack_size,
                "folder_unpack_size": archive.folder_unpack_size,
                "directories": archive.directories,
                "entries": [[e.name, e.size, f"{e.crc32:08x}" if e.crc32 is not None else None] for e in archive.entries],
            },
            indent=1,
        )
    )
    if args.extract_to:
        args.extract_to.mkdir(parents=True, exist_ok=True)
        for entry, payload in archive.iter_members():
            (args.extract_to / Path(entry.name).name).write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
