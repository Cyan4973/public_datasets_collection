"""Shared stdlib helpers for the M3D Motion (Zenodo 22811456) recipe.

ZIP central-directory / local-header parsing, raw-DEFLATE member inflation
with CRC-32 checks, mmWave Studio conf_file.cfg and DCA1000 LogFile.csv
parsing, and the TI HSI chirp-record splitter (64-byte header + 1024-byte
payload). Used by download.sh and build.sh through m3d_tool.py; verify.sh
uses its own independent implementation (verify_samples.py).
"""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
from pathlib import Path

ZIP_SIZE = 3_712_631_577
CD_OFFSET = 3_712_592_250
CD_SIZE = 39_305
CD_ENTRIES = 349
CD_SHA256 = "7038083082f33d9ba0e7dc2e1b82c35a07d6375ce6f3a74a4402eb3269064f4f"
ROOT = "dataset_260917/"

# One DCA1000 HSI record per chirp: 64-byte header (constant, starts with the
# 0x0CDA0ADC0CDA0ADC magic) + 1024-byte payload = 64 complex samples x 4 RX
# x (Q, I) int16.
HSI_HEADER = bytes.fromhex(
    "dc0ada0cdc0ada0c300400000000000080072000040200020f010100800000000000"
    "0000000000000000000000000000000000000f0f0f0f0f0f0f0f0f0f0f0f"
)
HSI_MAGIC = bytes.fromhex("dc0ada0cdc0ada0c")
HEADER_BYTES = 64
PAYLOAD_BYTES = 1024
RECORD_BYTES = HEADER_BYTES + PAYLOAD_BYTES
VALUES_PER_CHIRP = PAYLOAD_BYTES // 2

# Exact acquisition profile required of every selected capture.
REQUIRED_CFG_LINES = [
    "dfeDataOutputMode 1",
    "channelCfg 15 7 0",
    "adcCfg 2 1",
    "adcbufCfg -1 0 1 1 1",
    "profileCfg 0 61.2 60 17 50 657930 0 55.27 1 64 2000 2 1 36",
    "chirpCfg 0 0 0 0 0 0 0 1",
    "chirpCfg 1 1 0 0 0 0 0 2",
    "chirpCfg 2 2 0 0 0 0 0 4",
    "lvdsStreamCfg -1 1 1 1",
]
FRAME_RE = re.compile(r"^frameCfg 0 2 (\d+) 0 100 1 0$")
ALLOWED_LOOPS = {48, 64}

assert len(HSI_HEADER) == HEADER_BYTES and HSI_HEADER.startswith(HSI_MAGIC)


class FormatError(Exception):
    pass


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise FormatError(msg)


# ---------------------------------------------------------------- ZIP layer
def parse_central_directory(tail: bytes, tail_start: int) -> tuple[bytes, list[dict]]:
    """Locate EOCD in the archive tail, check the pinned CD geometry, parse entries."""
    i = tail.rfind(b"PK\x05\x06")
    require(i >= 0 and len(tail) - i >= 22, "EOCD not found in tail")
    _sig, disk, cd_disk, n_disk, n, cd_size, cd_off, _cl = struct.unpack("<IHHHHIIH", tail[i : i + 22])
    require(disk == 0 and cd_disk == 0 and n_disk == n, "multi-disk archive")
    require(tail.rfind(b"PK\x06\x06") < 0, "unexpected ZIP64 EOCD")
    require((n, cd_size, cd_off) == (CD_ENTRIES, CD_SIZE, CD_OFFSET),
            f"central directory geometry changed: entries={n} size={cd_size} offset={cd_off}")
    rel = cd_off - tail_start
    require(rel >= 0, "CD not inside tail")
    cd = tail[rel : rel + cd_size]
    require(len(cd) == cd_size and rel + cd_size == i, "CD not contiguous with EOCD")
    require(hashlib.sha256(cd).hexdigest() == CD_SHA256, "central directory SHA-256 differs from pin")
    entries = []
    p = 0
    for _ in range(n):
        (sig, _vm, _vn, flags, method, _mt, _md, crc, csize, usize, fnl, exl, cml,
         _dsk, _ia, _ea, lho) = struct.unpack("<IHHHHHHIIIHHHHHII", cd[p : p + 46])
        require(sig == 0x02014B50, f"bad CD signature at {p}")
        name = cd[p + 46 : p + 46 + fnl].decode("utf-8")
        require(0xFFFFFFFF not in (csize, usize, lho), f"ZIP64 field in {name}")
        entries.append({"name": name, "flags": flags, "method": method, "crc32": crc,
                        "csize": csize, "usize": usize, "lho": lho})
        p += 46 + fnl + exl + cml
    require(p == cd_size, "CD length mismatch")
    return cd, entries


def parse_local_header(blob: bytes, name: str, method: int, csize: int) -> int:
    """Return the data offset (relative to blob start) after validating the local header."""
    require(len(blob) >= 30, f"{name}: short local header")
    sig, _ver, flags, meth, _t, _d, _crc, _cs, _us, fnl, exl = struct.unpack("<IHHHHHIIIHH", blob[:30])
    require(sig == 0x04034B50, f"{name}: bad local header signature")
    require(meth == method, f"{name}: method {meth} != CD {method}")
    require(not flags & 1, f"{name}: encrypted")
    require(blob[30 : 30 + fnl].decode("utf-8") == name, f"{name}: local name mismatch")
    return 30 + fnl + exl


def inflate_iter(path: Path, data_offset: int, csize: int, chunk: int = 1 << 20):
    """Yield inflated chunks of a raw-DEFLATE member stored in a local range file."""
    with open(path, "rb") as fh:
        fh.seek(data_offset)
        d = zlib.decompressobj(-15)
        left = csize
        while left:
            buf = fh.read(min(chunk, left))
            require(len(buf) > 0, f"{path.name}: truncated compressed data")
            left -= len(buf)
            out = d.decompress(buf)
            if out:
                yield out
        tail = d.flush()
        if tail:
            yield tail
        require(d.eof, f"{path.name}: DEFLATE stream did not end at compressed size")
        require(not d.unused_data, f"{path.name}: trailing bytes after DEFLATE stream")


def inflate_member(path: Path, entry: dict, data_offset: int) -> bytes:
    raw = b"".join(inflate_iter(path, data_offset, entry["csize"]))
    require(len(raw) == entry["usize"], f"{entry['name']}: size {len(raw)} != {entry['usize']}")
    require(zlib.crc32(raw) == entry["crc32"], f"{entry['name']}: CRC-32 mismatch")
    return raw


# ------------------------------------------------------------ text members
def cfg_frame_loops(text: str) -> int | None:
    """Return loops per frame if the cfg is the pinned profile at 100 ms frames, else None."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for req in REQUIRED_CFG_LINES:
        if req not in lines:
            return None
    if sum(1 for ln in lines if ln.startswith("profileCfg")) != 1:
        return None
    if sum(1 for ln in lines if ln.startswith("chirpCfg")) != 3:
        return None
    frames = [ln for ln in lines if ln.startswith("frameCfg")]
    if len(frames) != 1:
        return None
    m = FRAME_RE.match(frames[0])
    if not m:
        return None
    return int(m.group(1))


def check_log(text: str, chirps: int) -> None:
    """DCA1000 LogFile.csv: the 0ADC stream must be complete and in order."""
    m = re.search(r"0ADC Header Data :(.*?)(?:\n\s*\n|\Z)", text, re.S)
    require(m is not None, "log: no 0ADC section")
    sec = m.group(1)

    def field(label: str) -> int:
        mm = re.search(re.escape(label) + r"\s*-\s*(\d+)", sec)
        require(mm is not None, f"log: missing {label}")
        return int(mm.group(1))

    require(field("Out of sequence count") == 0, "log: out-of-sequence packets")
    require(field("Number of zero filled packets") == 0, "log: zero-filled packets")
    require(field("Number of zero filled bytes") == 0, "log: zero-filled bytes")
    require(field("Number of received packets") == chirps, "log: packet count != chirp records")
    require(field("First Packet ID") == 1 and field("Last Packet ID") == chirps, "log: packet id range")


def legend_labels(text: str) -> dict[str, str]:
    out = {}
    for ln in text.splitlines():
        m = re.match(r"^\s*(\d\d)\s+(.*?)\s*$", ln)
        if m:
            out[m.group(1)] = re.sub(r"\s+", " ", m.group(2))
    return out


# --------------------------------------------------------------- HSI layer
def split_hsi(chunks, on_payload) -> tuple[int, int]:
    """Split an inflated chunk stream into 1088-byte HSI records.

    Every header must equal the pinned HSI_HEADER. on_payload(bytes) receives
    each 1024-byte payload. Returns (records, crc32 of the full stream)."""
    buf = bytearray()
    crc = 0
    records = 0
    for c in chunks:
        crc = zlib.crc32(c, crc)
        buf += c
        n = len(buf) // RECORD_BYTES
        if not n:
            continue
        mv = memoryview(buf)
        for k in range(n):
            o = k * RECORD_BYTES
            if mv[o : o + HEADER_BYTES] != HSI_HEADER:
                raise FormatError(f"HSI header mismatch at chirp {records + k}: {bytes(mv[o:o + 64]).hex()}")
            on_payload(mv[o + HEADER_BYTES : o + RECORD_BYTES])
        mv.release()
        del buf[: n * RECORD_BYTES]
        records += n
    require(len(buf) == 0, f"stream length not a multiple of {RECORD_BYTES} ({len(buf)} trailing bytes)")
    return records, crc
