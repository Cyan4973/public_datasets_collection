"""Shared pure-stdlib helpers for tumvi_euroc_1024_cam_frames_u16.

- pinned member table (scripts/members.tsv)
- GNU/ustar header walk over a byte-range prefix of a tar
- strict 16-bit grayscale PNG chunk validation and decode (zlib + all five
  scanline filters), big-endian samples -> native uint16 array
"""
from __future__ import annotations

import collections
import csv
import re
import struct
import sys
import zlib
from array import array
from pathlib import Path

DATASET_ID = "tumvi_euroc_1024_cam_frames_u16"
SERIES_ID = "tumvi_cam1_intensity_u16"
WIDTH = HEIGHT = 1024
PNG_SIG = b"\x89PNG\r\n\x1a\n"
MAX_MODE_FRACTION = 0.5


def member_regex(sequence: str) -> re.Pattern:
    return re.compile(rf"^dataset-{re.escape(sequence)}_1024_16/mav0/cam1/data/(\d{{19}})\.png$")


def load_members(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            r["tar_bytes"] = int(r["tar_bytes"])
            r["data_offset"] = int(r["data_offset"])
            r["size"] = int(r["size"])
            if not member_regex(r["sequence"]).match(r["member"]):
                raise ValueError(f"pinned member is not a cam1 PNG: {r['member']}")
            if r["tar"] != f"dataset-{r['sequence']}_1024_16.tar":
                raise ValueError(f"pinned tar name mismatch: {r}")
            rows.append(r)
    if not rows:
        raise ValueError("empty member table")
    return rows


def tar_prefixes(rows: list[dict]) -> "collections.OrderedDict[str, dict]":
    """tar name -> {sequence, tar_bytes, prefix_bytes, members[]} in table order."""
    out: collections.OrderedDict[str, dict] = collections.OrderedDict()
    for r in rows:
        t = out.setdefault(r["tar"], {"sequence": r["sequence"], "tar_bytes": r["tar_bytes"],
                                      "prefix_bytes": 0, "members": []})
        if t["tar_bytes"] != r["tar_bytes"] or t["sequence"] != r["sequence"]:
            raise ValueError(f"inconsistent tar metadata: {r}")
        t["members"].append(r)
        t["prefix_bytes"] = max(t["prefix_bytes"], r["data_offset"] + r["size"])
    return out


def _octal(field: bytes) -> int:
    s = field.split(b"\0")[0].strip()
    return int(s, 8) if s else 0


def walk_tar_prefix(buf: bytes):
    """Yield (name, typeflag, data_offset, size) for every member whose header
    and data lie fully inside `buf`. Stops at the end-of-archive block or at
    the first member that is not fully contained."""
    off = 0
    n = len(buf)
    while off + 512 <= n:
        h = buf[off:off + 512]
        if h == b"\0" * 512:
            return
        if _octal(h[148:156]) != sum(h[:148]) + 256 + sum(h[156:]):
            raise ValueError(f"tar header checksum mismatch at {off}")
        typ = h[156:157]
        if typ in (b"L", b"K", b"x", b"g"):
            raise ValueError(f"unsupported tar extension header {typ!r} at {off}")
        name = h[0:100].split(b"\0")[0].decode("utf-8")
        if h[257:263] == b"ustar\0":
            prefix = h[345:500].split(b"\0")[0].decode("utf-8")
            if prefix:
                name = prefix + "/" + name
        size = _octal(h[124:136])
        data_off = off + 512
        if data_off + size > n:
            return
        yield name, typ, data_off, size
        off = data_off + (size + 511) // 512 * 512


def png_chunks(data: bytes) -> list[tuple[bytes, bytes, int]]:
    """Return [(type, payload, crc)] after validating signature, every chunk
    CRC, and that IEND terminates the stream exactly."""
    if data[:8] != PNG_SIG:
        raise ValueError("not a PNG")
    pos, n = 8, len(data)
    chunks = []
    while True:
        if pos + 12 > n:
            raise ValueError("truncated PNG chunk")
        ln = struct.unpack_from(">I", data, pos)[0]
        ctype = data[pos + 4:pos + 8]
        end = pos + 12 + ln
        if end > n:
            raise ValueError("truncated PNG chunk payload")
        payload = data[pos + 8:pos + 8 + ln]
        crc = struct.unpack_from(">I", data, pos + 8 + ln)[0]
        if zlib.crc32(ctype + payload) & 0xFFFFFFFF != crc:
            raise ValueError(f"PNG chunk CRC mismatch for {ctype!r}")
        chunks.append((ctype, payload, crc))
        pos = end
        if ctype == b"IEND":
            break
    if pos != n:
        raise ValueError("trailing bytes after IEND")
    if chunks[0][0] != b"IHDR":
        raise ValueError("first chunk is not IHDR")
    return chunks


def last_idat_crc(chunks) -> str:
    idats = [c for c in chunks if c[0] == b"IDAT"]
    if not idats:
        raise ValueError("no IDAT")
    return f"{idats[-1][2]:08x}"


def ihdr(chunks) -> tuple[int, int, int, int, int, int, int]:
    return struct.unpack(">IIBBBBB", chunks[0][1])


def unfilter(raw: bytes, width: int, height: int, bpp: int) -> bytearray:
    stride = width * bpp
    if len(raw) != (stride + 1) * height:
        raise ValueError(f"bad inflated size {len(raw)} != {(stride + 1) * height}")
    out = bytearray(height * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 0:
            pass
        elif ft == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:  # Average
            for i in range(bpp):
                line[i] = (line[i] + (prev[i] >> 1)) & 0xFF
            for i in range(bpp, stride):
                line[i] = (line[i] + ((line[i - bpp] + prev[i]) >> 1)) & 0xFF
        elif ft == 4:  # Paeth
            for i in range(bpp):
                line[i] = (line[i] + prev[i]) & 0xFF  # a = c = 0 -> predictor b
            for i in range(bpp, stride):
                a = line[i - bpp]
                b = prev[i]
                c = prev[i - bpp]
                pa = b - c
                pb = a - c
                pc = pa + pb
                if pa < 0:
                    pa = -pa
                if pb < 0:
                    pb = -pb
                if pc < 0:
                    pc = -pc
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                line[i] = (line[i] + pr) & 0xFF
        else:
            raise ValueError(f"bad PNG filter type {ft}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def decode_png_gray16(data: bytes, expect_w: int = WIDTH, expect_h: int = HEIGHT):
    """Strictly decode a non-interlaced 16-bit grayscale PNG.

    Returns (chunks, values) where values is an array('H') of native uint16
    pixel values in row-major order."""
    chunks = png_chunks(data)
    w, h, depth, ctype, comp, filt, interlace = ihdr(chunks)
    if (w, h, depth, ctype, comp, filt, interlace) != (expect_w, expect_h, 16, 0, 0, 0, 0):
        raise ValueError(f"unexpected IHDR {(w, h, depth, ctype, comp, filt, interlace)}")
    idat = b"".join(p for t, p, _ in chunks if t == b"IDAT")
    d = zlib.decompressobj()
    raw = d.decompress(idat)
    raw += d.flush()
    if not d.eof or d.unused_data:
        raise ValueError("zlib stream not cleanly terminated")
    pix = unfilter(raw, w, h, 2)
    vals = array("H")
    vals.frombytes(bytes(pix))
    if sys.byteorder == "little":
        vals.byteswap()  # PNG samples are big-endian
    return chunks, vals


def frame_stats(vals: array) -> dict:
    counts = collections.Counter(vals)
    mode_value, mode_count = counts.most_common(1)[0]
    low_nibble_nonzero = sum(c for v, c in counts.items() if v & 0xF)
    return {
        "min": min(counts),
        "max": max(counts),
        "distinct": len(counts),
        "mode_value": int(mode_value),
        "mode_fraction": round(mode_count / len(vals), 6),
        "low_nibble_nonzero": int(low_nibble_nonzero),
    }


def le_bytes(vals: array) -> bytes:
    if sys.byteorder == "little":
        return vals.tobytes()
    out = array("H", vals)
    out.byteswap()
    return out.tobytes()


def sample_name(row: dict) -> str:
    ts = member_regex(row["sequence"]).match(row["member"]).group(1)
    return f"{row['sequence']}_cam1_{ts}.bin"
