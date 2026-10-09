#!/usr/bin/env python3
"""Pure-standard-library LAZ (LASzip) decoder.

Decodes LASzip-compressed point clouds (.laz) back into the uncompressed LAS
point records they were made from, byte for byte, with nothing but the Python
3 standard library (no numpy, no laszip/lazrs bindings).

Supported:
  * LAS header 1.0 - 1.4, VLRs, EVLRs, the LASzip VLR (user_id
    "laszip encoded", record_id 22204).
  * Compressor 1 (point-wise, one chunk) and 2 (point-wise chunked) with the
    version 2 items POINT10, GPSTIME11, RGB12 and BYTE: point formats 0-3
    plus extra bytes.
  * Compressor 3 (layered chunked, "native LAS 1.4") with the version 3 items
    POINT14, RGB14, RGBNIR14 and BYTE14: point formats 6, 7 and 8 plus extra
    bytes.
  * Fixed and variable chunk sizes, the compressed chunk table, the
    "chunk table offset = -1" (offset stored at the end of the file) case and
    files without a chunk table (decoded sequentially).

Rejected with a clear LazError: wave packet items (point formats 4, 5, 9, 10),
version 1 items (LASzip 1.x files), item version 4, unknown coders.

The algorithms (adaptive arithmetic decoder, symbol and bit models, integer
corrector decompressor, item predictors) follow the LAZ specification by
rapidlasso and were checked against the LASzip (C++, Apache-2.0) and laz-rs
(Rust, Apache-2.0) reference implementations. This is an independent Python
implementation; see tools/laz/README.md for attribution and validation.

API:
  read_header(path) -> dict
  decode_points(path, max_points=None) -> (header, bytes)
  iter_chunks(path, max_points=None) -> iterator of (chunk_index, n, bytes)

CLI:
  python3 tools/laz/laszip.py info file.laz
  python3 tools/laz/laszip.py decode file.laz out.las [--max-points N]
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from bisect import bisect_right
from itertools import accumulate


class LazError(Exception):
    """Raised for unsupported or corrupt LAS/LAZ input."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LASZIP_USER_ID = "laszip encoded"
LASZIP_RECORD_ID = 22204

COMPRESSOR_NONE = 0
COMPRESSOR_POINTWISE = 1
COMPRESSOR_POINTWISE_CHUNKED = 2
COMPRESSOR_LAYERED_CHUNKED = 3
COMPRESSOR_NAMES = {
    0: "none",
    1: "pointwise",
    2: "pointwise_chunked",
    3: "layered_chunked",
}

ITEM_BYTE = 0
ITEM_POINT10 = 6
ITEM_GPSTIME11 = 7
ITEM_RGB12 = 8
ITEM_WAVEPACKET13 = 9
ITEM_POINT14 = 10
ITEM_RGB14 = 11
ITEM_RGBNIR14 = 12
ITEM_WAVEPACKET14 = 13
ITEM_BYTE14 = 14
ITEM_NAMES = {
    0: "BYTE",
    1: "SHORT",
    2: "INT",
    3: "LONG",
    4: "FLOAT",
    5: "DOUBLE",
    6: "POINT10",
    7: "GPSTIME11",
    8: "RGB12",
    9: "WAVEPACKET13",
    10: "POINT14",
    11: "RGB14",
    12: "RGBNIR14",
    13: "WAVEPACKET14",
    14: "BYTE14",
}
ITEM_FIXED_SIZES = {
    ITEM_POINT10: 20,
    ITEM_GPSTIME11: 8,
    ITEM_RGB12: 6,
    ITEM_WAVEPACKET13: 29,
    ITEM_POINT14: 30,
    ITEM_RGB14: 6,
    ITEM_RGBNIR14: 8,
    ITEM_WAVEPACKET14: 29,
}

# Size of the standard fields of each LAS point data record format.
POINT_FORMAT_SIZES = {0: 20, 1: 28, 2: 26, 3: 34, 4: 57, 5: 63, 6: 30, 7: 36, 8: 38, 9: 59, 10: 67}

VARIABLE_CHUNK_SIZE = 0xFFFFFFFF

# Arithmetic coder constants (LAZ specification).
AC_MIN_LENGTH = 0x01000000
AC_MAX_LENGTH = 0xFFFFFFFF
DM_LENGTH_SHIFT = 15
DM_MAX_COUNT = 1 << DM_LENGTH_SHIFT
BM_LENGTH_SHIFT = 13
BM_MAX_COUNT = 1 << BM_LENGTH_SHIFT

MASK32 = 0xFFFFFFFF
MASK64 = 0xFFFFFFFFFFFFFFFF

# Zero bytes appended to every compressed buffer so the decoder never needs a
# bounds check while renormalising. Valid streams never read into it.
_PAD = bytes(16)

# ---------------------------------------------------------------------------
# LAS header, VLRs, LASzip VLR
# ---------------------------------------------------------------------------

_HEADER_BASE = struct.Struct("<4sHHIHH8sBB32s32sHHHIIBHI5I3d3d6d")  # 227 bytes


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("latin-1").rstrip()


def parse_laszip_vlr(data: bytes) -> dict:
    """Parse the payload of the LASzip VLR (record 22204)."""
    if len(data) < 34:
        raise LazError(f"LASzip VLR too short ({len(data)} bytes)")
    (compressor, coder, ver_major, ver_minor, ver_rev, options, chunk_size,
     num_special_evlrs, offset_special_evlrs, num_items) = struct.unpack_from("<HHBBHIIqqH", data, 0)
    if len(data) < 34 + 6 * num_items:
        raise LazError("LASzip VLR item list is truncated")
    items = []
    for i in range(num_items):
        itype, isize, iversion = struct.unpack_from("<HHH", data, 34 + 6 * i)
        items.append({
            "type": itype,
            "name": ITEM_NAMES.get(itype, f"UNKNOWN{itype}"),
            "size": isize,
            "version": iversion,
        })
    return {
        "compressor": compressor,
        "compressor_name": COMPRESSOR_NAMES.get(compressor, f"unknown{compressor}"),
        "coder": coder,
        "version": f"{ver_major}.{ver_minor}r{ver_rev}",
        "options": options,
        "chunk_size": chunk_size,
        "variable_chunks": chunk_size in (0, VARIABLE_CHUNK_SIZE),
        "number_of_special_evlrs": num_special_evlrs,
        "offset_to_special_evlrs": offset_special_evlrs,
        "items": items,
    }


def _parse_header_bytes(raw: bytes, file_size: int) -> dict:
    if len(raw) < 227 or raw[:4] != b"LASF":
        raise LazError("not a LAS/LAZ file (missing LASF signature or short header)")
    f = _HEADER_BASE.unpack_from(raw, 0)
    (sig, file_source_id, global_encoding, guid1, guid2, guid3, guid4, vmaj, vmin, system_id,
     software, day, year, header_size, offset_to_points, num_vlrs, fmt_raw, record_length,
     legacy_count) = f[:19]
    legacy_by_return = list(f[19:24])
    scale = f[24:27]
    offset = f[27:30]
    max_x, min_x, max_y, min_y, max_z, min_z = f[30:36]
    hdr = {
        "file_size": file_size,
        "file_source_id": file_source_id,
        "global_encoding": global_encoding,
        "project_guid": struct.pack("<IHH", guid1, guid2, guid3).hex() + guid4.hex(),
        "version_major": vmaj,
        "version_minor": vmin,
        "version": f"{vmaj}.{vmin}",
        "system_identifier": _cstr(system_id),
        "generating_software": _cstr(software),
        "creation_day_of_year": day,
        "creation_year": year,
        "header_size": header_size,
        "offset_to_point_data": offset_to_points,
        "number_of_vlrs": num_vlrs,
        "point_format_raw": fmt_raw,
        "point_format": fmt_raw & 0x3F,
        "compressed": bool(fmt_raw & 0xC0),
        "point_record_length": record_length,
        "legacy_point_count": legacy_count,
        "legacy_points_by_return": legacy_by_return,
        "scale": tuple(scale),
        "offset": tuple(offset),
        "min": (min_x, min_y, min_z),
        "max": (max_x, max_y, max_z),
        "start_of_waveform_data": 0,
        "start_of_first_evlr": 0,
        "number_of_evlrs": 0,
        "point_count_64": None,
        "points_by_return_64": None,
    }
    if header_size < 227:
        raise LazError(f"header size {header_size} is smaller than 227")
    if (vmaj, vmin) >= (1, 3) and header_size >= 235 and len(raw) >= 235:
        (hdr["start_of_waveform_data"],) = struct.unpack_from("<Q", raw, 227)
    if (vmaj, vmin) >= (1, 4) and header_size >= 375 and len(raw) >= 375:
        start_evlr, num_evlrs, count64 = struct.unpack_from("<QIQ", raw, 235)
        hdr["start_of_first_evlr"] = start_evlr
        hdr["number_of_evlrs"] = num_evlrs
        hdr["point_count_64"] = count64
        hdr["points_by_return_64"] = list(struct.unpack_from("<15Q", raw, 255))
    count = legacy_count
    if hdr["point_count_64"]:
        count = hdr["point_count_64"]
    hdr["point_count"] = count
    std = POINT_FORMAT_SIZES.get(hdr["point_format"])
    hdr["extra_bytes_per_point"] = (record_length - std) if std is not None else None
    return hdr


def read_header(path: str) -> dict:
    """Read the LAS/LAZ header, VLRs, EVLR directory and LASzip VLR.

    Returns a dict. Main keys: version, point_format (compression bits
    cleared), point_record_length, point_count (64-bit count for LAS 1.4),
    scale, offset, min, max, offset_to_point_data, compressed, vlrs (list of
    dicts with user_id, record_id, description, data_offset, length), evlrs,
    laszip (parsed LASzip VLR or None).
    """
    file_size = os.path.getsize(path)
    with open(path, "rb") as fh:
        raw = fh.read(375)
        hdr = _parse_header_bytes(raw, file_size)
        fh.seek(0)
        prefix = fh.read(hdr["offset_to_point_data"])
        hdr["vlrs"] = _parse_vlrs(prefix, hdr)
        hdr["evlrs"] = _parse_evlrs(fh, hdr)
    hdr["path"] = path
    hdr["laszip"] = None
    for vlr in hdr["vlrs"]:
        if vlr["user_id"] == LASZIP_USER_ID and vlr["record_id"] == LASZIP_RECORD_ID:
            hdr["laszip"] = parse_laszip_vlr(vlr["data"])
    if hdr["compressed"] and hdr["laszip"] is None:
        raise LazError("point format has the compression bit set but no LASzip VLR was found")
    return hdr


def _parse_vlrs(prefix: bytes, hdr: dict) -> list:
    vlrs = []
    pos = hdr["header_size"]
    for i in range(hdr["number_of_vlrs"]):
        if pos + 54 > len(prefix):
            raise LazError(f"VLR {i} header runs past the start of point data")
        user_id = _cstr(prefix[pos + 2:pos + 18])
        record_id, length = struct.unpack_from("<HH", prefix, pos + 18)
        description = _cstr(prefix[pos + 22:pos + 54])
        data_offset = pos + 54
        if data_offset + length > len(prefix):
            raise LazError(f"VLR {i} ({user_id}/{record_id}) runs past the start of point data")
        vlrs.append({
            "user_id": user_id,
            "record_id": record_id,
            "description": description,
            "header_offset": pos,
            "data_offset": data_offset,
            "length": length,
            "data": prefix[data_offset:data_offset + length],
        })
        pos = data_offset + length
    hdr["end_of_vlrs"] = pos
    return vlrs


def _parse_evlrs(fh, hdr: dict) -> list:
    evlrs = []
    count = hdr["number_of_evlrs"]
    pos = hdr["start_of_first_evlr"]
    if not count or not pos:
        return evlrs
    for i in range(count):
        fh.seek(pos)
        raw = fh.read(60)
        if len(raw) < 60:
            raise LazError(f"EVLR {i} header is truncated")
        user_id = _cstr(raw[2:18])
        record_id, length = struct.unpack_from("<HQ", raw, 18)
        evlrs.append({
            "user_id": user_id,
            "record_id": record_id,
            "description": _cstr(raw[28:60]),
            "header_offset": pos,
            "data_offset": pos + 60,
            "length": length,
        })
        pos += 60 + length
    hdr["end_of_evlrs"] = pos
    return evlrs


# ---------------------------------------------------------------------------
# Entropy models
# ---------------------------------------------------------------------------

class ArithmeticModel:
    """Adaptive multi-symbol model (LAZ spec 'ArithmeticModel', decoder side).

    `distribution[k]` is the scaled cumulative count of the symbols below k,
    rebuilt by update() every `update_cycle` symbols exactly like LASzip.
    LASzip additionally keeps a coarse 'decoder table' to speed up its
    search for the symbol; this module finds the same symbol with
    bisect_right() over `distribution` instead (identical result, since the
    distribution is strictly increasing), so no table is needed.
    """

    __slots__ = ("symbols", "last_symbol", "distribution", "symbol_count", "total_count",
                 "update_cycle", "symbols_until_update")

    def __init__(self, symbols: int):
        template = _MODEL_TEMPLATES.get(symbols)
        if template is None:
            template = _make_model_template(symbols)
        dist, counts, total, cycle, until = template
        self.symbols = symbols
        self.last_symbol = symbols - 1
        self.distribution = dist  # never mutated in place, safe to share
        self.symbol_count = counts[:]
        self.total_count = total
        self.update_cycle = cycle
        self.symbols_until_update = until

    def update(self) -> None:
        counts = self.symbol_count
        self.total_count += self.update_cycle
        if self.total_count > DM_MAX_COUNT:
            counts[:] = [(c + 1) >> 1 for c in counts]
            self.total_count = sum(counts)
        scale = 0x80000000 // self.total_count
        # scaled cumulative counts below each symbol: (scale * cum) >> (31 - 15)
        dist = [(scale * c) >> 16 for c in accumulate(counts, initial=0)]
        del dist[-1]
        self.distribution = dist
        cycle = (5 * self.update_cycle) >> 2
        max_cycle = (self.symbols + 6) << 3
        if cycle > max_cycle:
            cycle = max_cycle
        self.update_cycle = cycle
        self.symbols_until_update = cycle


def _make_model_template(symbols: int) -> tuple:
    """Initial state of a fresh model with `symbols` symbols (all counts 1)."""
    if symbols < 2 or symbols > (1 << 11):
        raise LazError(f"invalid number of model symbols {symbols}")
    model = ArithmeticModel.__new__(ArithmeticModel)
    model.symbols = symbols
    model.last_symbol = symbols - 1
    model.symbol_count = [1] * symbols
    model.total_count = 0
    model.update_cycle = symbols
    model.update()
    model.update_cycle = (symbols + 6) >> 1
    model.symbols_until_update = (symbols + 6) >> 1
    template = (model.distribution, model.symbol_count, model.total_count,
                model.update_cycle, model.symbols_until_update)
    _MODEL_TEMPLATES[symbols] = template
    return template


_MODEL_TEMPLATES: dict = {}


class ArithmeticBitModel:
    """Adaptive binary model (LAZ spec 'ArithmeticBitModel')."""

    __slots__ = ("bit_0_count", "bit_count", "bit_0_prob", "bits_until_update", "update_cycle")

    def __init__(self):
        self.bit_0_count = 1
        self.bit_count = 2
        self.bit_0_prob = 1 << (BM_LENGTH_SHIFT - 1)
        self.bits_until_update = 4
        self.update_cycle = 4

    def update(self) -> None:
        self.bit_count += self.update_cycle
        if self.bit_count > BM_MAX_COUNT:
            self.bit_count = (self.bit_count + 1) >> 1
            self.bit_0_count = (self.bit_0_count + 1) >> 1
            if self.bit_0_count == self.bit_count:
                self.bit_count += 1
        scale = 0x80000000 // self.bit_count
        self.bit_0_prob = (self.bit_0_count * scale) >> (31 - BM_LENGTH_SHIFT)
        cycle = (5 * self.update_cycle) >> 2
        if cycle > 64:
            cycle = 64
        self.update_cycle = cycle
        self.bits_until_update = cycle


# ---------------------------------------------------------------------------
# Arithmetic decoder
# ---------------------------------------------------------------------------

class ArithmeticDecoder:
    """Range decoder over an in-memory buffer (LAZ spec 'ArithmeticDecoder').

    `buf` must be followed by at least 4 padding bytes past `end`; reads past
    the real data return those zero bytes, like LASzip's encoder flush expects.
    """

    __slots__ = ("buf", "pos", "value", "length")

    def __init__(self, buf: bytes, pos: int = 0):
        self.buf = buf
        self.value = int.from_bytes(buf[pos:pos + 4], "big")
        self.pos = pos + 4
        self.length = AC_MAX_LENGTH

    # The hot methods below use literal constants: 0x1000000 = AC_MIN_LENGTH,
    # 13 = BM_LENGTH_SHIFT, 15 = DM_LENGTH_SHIFT.

    def decode_bit(self, m: ArithmeticBitModel) -> int:
        x = m.bit_0_prob * (self.length >> 13)
        value = self.value
        if value < x:
            length = x
            m.bit_0_count += 1
            sym = 0
        else:
            value -= x
            length = self.length - x
            sym = 1
        if length < 0x1000000:
            buf = self.buf
            pos = self.pos
            while length < 0x1000000:
                value = (value << 8) | buf[pos]
                pos += 1
                length <<= 8
            self.pos = pos
        self.value = value
        self.length = length
        u = m.bits_until_update - 1
        if u:
            m.bits_until_update = u
        else:
            m.update()
        return sym

    def decode_symbol(self, m: ArithmeticModel) -> int:
        value = self.value
        length = self.length >> 15
        dist = m.distribution
        # the symbol whose interval [dist[s], dist[s+1]) holds value // length
        sym = bisect_right(dist, value // length) - 1
        x = dist[sym] * length
        if sym != m.last_symbol:
            length = dist[sym + 1] * length - x
        else:
            length = self.length - x
        value -= x
        if length < 0x1000000:
            buf = self.buf
            pos = self.pos
            while length < 0x1000000:
                value = (value << 8) | buf[pos]
                pos += 1
                length <<= 8
            self.pos = pos
        self.value = value
        self.length = length
        m.symbol_count[sym] += 1
        u = m.symbols_until_update - 1
        if u:
            m.symbols_until_update = u
        else:
            m.update()
        return sym

    def read_bits(self, bits: int) -> int:
        if bits > 19:
            low = self.read_bits(16)
            return (self.read_bits(bits - 16) << 16) | low
        length = self.length >> bits
        value = self.value
        sym = value // length
        value -= length * sym
        if length < 0x1000000:
            buf = self.buf
            pos = self.pos
            while length < 0x1000000:
                value = (value << 8) | buf[pos]
                pos += 1
                length <<= 8
            self.pos = pos
        self.value = value
        self.length = length
        return sym

    def read_int(self) -> int:
        low = self.read_bits(16)
        return (self.read_bits(16) << 16) | low


# ---------------------------------------------------------------------------
# Integer (corrector) decompressor
# ---------------------------------------------------------------------------

class IntegerDecompressor:
    """LAZ spec 'IntegerCompressor' (decompress side).

    decompress() returns pred + corrector, wrapped into [0, 2**bits) for
    bits < 32 and into the signed int32 range for bits == 32. After each call
    `k` holds the number of significant corrector bits (used as a context by
    later fields).
    """

    __slots__ = ("k", "corr_bits", "corr_range", "corr_min", "bits_high", "m_bits",
                 "m_corrector0", "m_corrector")

    def __init__(self, bits: int = 16, contexts: int = 1, bits_high: int = 8):
        # (LASzip also accepts an explicit 'range'; no LAZ item uses it)
        if 0 < bits < 32:
            corr_bits = bits
            corr_range = 1 << bits
            corr_min = -(corr_range // 2)
        else:
            corr_bits = 32
            corr_range = 0
            corr_min = -0x80000000
        self.k = 0
        self.corr_bits = corr_bits
        self.corr_range = corr_range
        self.corr_min = corr_min
        self.bits_high = bits_high
        self.m_bits = [ArithmeticModel(corr_bits + 1) for _ in range(contexts)]
        self.m_corrector0 = ArithmeticBitModel()
        # index k (1..corr_bits); created on first use, which is equivalent
        # to LASzip creating and initialising all of them up front
        self.m_corrector = [None] * (corr_bits + 1)

    def decompress(self, dec: ArithmeticDecoder, pred: int, context: int = 0) -> int:
        # k = dec.decode_symbol(self.m_bits[context]), inlined (hottest path)
        m = self.m_bits[context]
        value = dec.value
        length = dec.length >> 15
        dist = m.distribution
        k = bisect_right(dist, value // length) - 1
        x = dist[k] * length
        if k != m.last_symbol:
            length = dist[k + 1] * length - x
        else:
            length = dec.length - x
        value -= x
        if length < 0x1000000:
            buf = dec.buf
            pos = dec.pos
            while length < 0x1000000:
                value = (value << 8) | buf[pos]
                pos += 1
                length <<= 8
            dec.pos = pos
        dec.value = value
        dec.length = length
        m.symbol_count[k] += 1
        u = m.symbols_until_update - 1
        if u:
            m.symbols_until_update = u
        else:
            m.update()
        self.k = k
        if k:
            if k < 32:
                m = self.m_corrector[k]
                bits_high = self.bits_high
                if m is None:
                    m = self.m_corrector[k] = ArithmeticModel(1 << (k if k <= bits_high else bits_high))
                c = dec.decode_symbol(m)
                if k > bits_high:
                    k1 = k - bits_high
                    c = (c << k1) | dec.read_bits(k1)
                if c >= (1 << (k - 1)):
                    c += 1
                else:
                    c -= (1 << k) - 1
            else:
                c = self.corr_min
        else:
            c = dec.decode_bit(self.m_corrector0)
        real = pred + c
        corr_range = self.corr_range
        if corr_range:
            if real < 0:
                real += corr_range
            elif real >= corr_range:
                real -= corr_range
        elif real > 0x7FFFFFFF:
            real -= 0x100000000
        elif real < -0x80000000:
            real += 0x100000000
        return real


# ---------------------------------------------------------------------------
# Helpers shared by the item decoders
# ---------------------------------------------------------------------------

class StreamingMedian5:
    """Running median of the last five values (LASzip StreamingMedian5).

    The current median is `v[2]` (read directly by the item decoders).
    """

    __slots__ = ("v", "high")

    def __init__(self):
        self.v = [0, 0, 0, 0, 0]
        self.high = True

    def add(self, x: int) -> None:
        v = self.v
        if self.high:
            if x < v[2]:
                v[4] = v[3]
                v[3] = v[2]
                if x < v[0]:
                    v[2] = v[1]
                    v[1] = v[0]
                    v[0] = x
                elif x < v[1]:
                    v[2] = v[1]
                    v[1] = x
                else:
                    v[2] = x
            else:
                if x < v[3]:
                    v[4] = v[3]
                    v[3] = x
                else:
                    v[4] = x
                self.high = False
        else:
            if v[2] < x:
                v[0] = v[1]
                v[1] = v[2]
                if v[4] < x:
                    v[2] = v[3]
                    v[3] = v[4]
                    v[4] = x
                elif v[3] < x:
                    v[2] = v[3]
                    v[3] = x
                else:
                    v[2] = x
            else:
                if v[1] < x:
                    v[0] = v[1]
                    v[1] = x
                else:
                    v[0] = x
                self.high = True


def _i32(v: int) -> int:
    v &= MASK32
    return v - 0x100000000 if v & 0x80000000 else v


# number_return_map[n][r] and number_return_level[n][r] for POINT10 (3-bit r, n)
NUMBER_RETURN_MAP = (
    (15, 14, 13, 12, 11, 10, 9, 8),
    (14, 0, 1, 3, 6, 10, 10, 9),
    (13, 1, 2, 4, 7, 11, 11, 10),
    (12, 3, 4, 5, 8, 12, 12, 11),
    (11, 6, 7, 8, 9, 13, 13, 12),
    (10, 10, 11, 12, 13, 14, 14, 13),
    (9, 10, 11, 12, 13, 14, 15, 14),
    (8, 9, 10, 11, 12, 13, 14, 15),
)
NUMBER_RETURN_LEVEL = tuple(tuple(abs(n - r) for r in range(8)) for n in range(8))

# number_return_map_6ctx[n][r] and number_return_level_8ctx[n][r] for POINT14
NUMBER_RETURN_MAP_6CTX = (
    (0, 1, 2, 3, 4, 5, 3, 4, 4, 5, 5, 5, 5, 5, 5, 5),
    (1, 0, 1, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3),
    (2, 1, 2, 4, 4, 4, 4, 4, 4, 4, 4, 3, 3, 3, 3, 3),
    (3, 3, 4, 5, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    (4, 3, 4, 4, 5, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    (5, 3, 4, 4, 4, 5, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    (3, 3, 4, 4, 4, 4, 5, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    (4, 3, 4, 4, 4, 4, 4, 5, 4, 4, 4, 4, 4, 4, 4, 4),
    (4, 3, 4, 4, 4, 4, 4, 4, 5, 4, 4, 4, 4, 4, 4, 4),
    (5, 3, 4, 4, 4, 4, 4, 4, 4, 5, 4, 4, 4, 4, 4, 4),
    (5, 3, 4, 4, 4, 4, 4, 4, 4, 4, 5, 4, 4, 4, 4, 4),
    (5, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 4, 4, 4),
    (5, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 4, 4),
    (5, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 4),
    (5, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5),
    (5, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5),
)
NUMBER_RETURN_LEVEL_8CTX = tuple(tuple(min(abs(n - r), 7) for r in range(16)) for n in range(16))


def _new_rgb_models() -> list:
    # [bytes_used, lower red, upper red, lower green, upper green, lower blue, upper blue]
    return [ArithmeticModel(128)] + [ArithmeticModel(256) for _ in range(6)]


def _decode_rgb(dec: ArithmeticDecoder, m: list, last: tuple) -> tuple:
    """RGB12 v2 / RGB14 v3 colour predictor; returns the new (r, g, b)."""
    lr, lg, lb = last
    decode = dec.decode_symbol
    sym = decode(m[0])
    if sym & 1:
        r = (decode(m[1]) + (lr & 0xFF)) & 0xFF
    else:
        r = lr & 0xFF
    if sym & 2:
        r |= ((decode(m[2]) + (lr >> 8)) & 0xFF) << 8
    else:
        r |= lr & 0xFF00
    if sym & 64:
        diff = (r & 0xFF) - (lr & 0xFF)
        if sym & 4:
            p = diff + (lg & 0xFF)
            p = 0 if p < 0 else (255 if p > 255 else p)
            g = (decode(m[3]) + p) & 0xFF
        else:
            g = lg & 0xFF
        if sym & 16:
            d = diff + (g & 0xFF) - (lg & 0xFF)
            d = (d + (d < 0)) >> 1  # C integer division by 2 (truncates)
            p = d + (lb & 0xFF)
            p = 0 if p < 0 else (255 if p > 255 else p)
            b = (decode(m[5]) + p) & 0xFF
        else:
            b = lb & 0xFF
        diff = (r >> 8) - (lr >> 8)
        if sym & 8:
            p = diff + (lg >> 8)
            p = 0 if p < 0 else (255 if p > 255 else p)
            g |= ((decode(m[4]) + p) & 0xFF) << 8
        else:
            g |= lg & 0xFF00
        if sym & 32:
            d = diff + (g >> 8) - (lg >> 8)
            d = (d + (d < 0)) >> 1
            p = d + (lb >> 8)
            p = 0 if p < 0 else (255 if p > 255 else p)
            b |= ((decode(m[6]) + p) & 0xFF) << 8
        else:
            b |= lb & 0xFF00
    else:
        g = b = r
    return (r, g, b)


def _decode_nir(dec: ArithmeticDecoder, m: list, last: int) -> int:
    """RGBNIR14 v3 NIR predictor; m = [bytes_used(4), lower, upper]."""
    sym = dec.decode_symbol(m[0])
    if sym & 1:
        v = (dec.decode_symbol(m[1]) + (last & 0xFF)) & 0xFF
    else:
        v = last & 0xFF
    if sym & 2:
        v |= ((dec.decode_symbol(m[2]) + (last >> 8)) & 0xFF) << 8
    else:
        v |= last & 0xFF00
    return v


# ---------------------------------------------------------------------------
# Version 2 point-wise items (compressors 1 and 2)
# ---------------------------------------------------------------------------

_P10 = struct.Struct("<IIiHBBBBH")
_U64 = struct.Struct("<Q")
_RGB = struct.Struct("<HHH")

GPS_MULTI = 500
GPS_MULTI_MINUS = -10
GPS11_MULTI_UNCHANGED = GPS_MULTI - GPS_MULTI_MINUS + 1   # 511
GPS11_MULTI_CODE_FULL = GPS_MULTI - GPS_MULTI_MINUS + 2   # 512
GPS11_MULTI_TOTAL = GPS_MULTI - GPS_MULTI_MINUS + 6       # 516


class Point10V2:
    """POINT10 version 2: the 20-byte core of point formats 0-5."""

    size = 20

    def __init__(self):
        self.m_changed = ArithmeticModel(64)
        self.m_scan_angle = [ArithmeticModel(256), ArithmeticModel(256)]
        self.m_bit_byte = [None] * 256
        self.m_class = [None] * 256
        self.m_user = [None] * 256
        self.ic_intensity = IntegerDecompressor(16, 4)
        self.ic_psid = IntegerDecompressor(16, 1)
        self.ic_dx = IntegerDecompressor(32, 2)
        self.ic_dy = IntegerDecompressor(32, 22)
        self.ic_z = IntegerDecompressor(32, 20)
        self.last_intensity = [0] * 16
        self.med_x = [StreamingMedian5() for _ in range(16)]
        self.med_y = [StreamingMedian5() for _ in range(16)]
        self.last_height = [0] * 8
        self.state = None

    def init(self, raw: bytes) -> None:
        x, y, z, intensity, bits, cls, sar, ud, psid = _P10.unpack(raw)
        # LASzip resets the intensity of the reference point to 0
        self.state = [x, y, z, 0, bits, cls, sar, ud, psid]

    def decode(self, dec: ArithmeticDecoder, out: bytearray, off: int) -> None:
        x, y, z, intensity, bits, cls, sar, ud, psid = self.state
        changed = dec.decode_symbol(self.m_changed)
        if changed:
            if changed & 32:
                m = self.m_bit_byte[bits]
                if m is None:
                    m = self.m_bit_byte[bits] = ArithmeticModel(256)
                bits = dec.decode_symbol(m)
            r = bits & 7
            n = (bits >> 3) & 7
            mi = NUMBER_RETURN_MAP[n][r]
            li = NUMBER_RETURN_LEVEL[n][r]
            if changed & 16:
                intensity = self.ic_intensity.decompress(dec, self.last_intensity[mi], mi if mi < 3 else 3)
                self.last_intensity[mi] = intensity
            else:
                intensity = self.last_intensity[mi]
            if changed & 8:
                m = self.m_class[cls]
                if m is None:
                    m = self.m_class[cls] = ArithmeticModel(256)
                cls = dec.decode_symbol(m)
            if changed & 4:
                sar = (dec.decode_symbol(self.m_scan_angle[(bits >> 6) & 1]) + sar) & 0xFF
            if changed & 2:
                m = self.m_user[ud]
                if m is None:
                    m = self.m_user[ud] = ArithmeticModel(256)
                ud = dec.decode_symbol(m)
            if changed & 1:
                psid = self.ic_psid.decompress(dec, psid, 0)
        else:
            r = bits & 7
            n = (bits >> 3) & 7
            mi = NUMBER_RETURN_MAP[n][r]
            li = NUMBER_RETURN_LEVEL[n][r]
        n1 = 1 if n == 1 else 0
        med = self.med_x[mi]
        diff = self.ic_dx.decompress(dec, med.v[2], n1)
        x = (x + diff) & MASK32
        med.add(diff)
        k_bits = self.ic_dx.k
        med = self.med_y[mi]
        diff = self.ic_dy.decompress(dec, med.v[2], n1 + ((k_bits & ~1) if k_bits < 20 else 20))
        y = (y + diff) & MASK32
        med.add(diff)
        k_bits = (self.ic_dx.k + self.ic_dy.k) >> 1
        z = self.ic_z.decompress(dec, self.last_height[li], n1 + ((k_bits & ~1) if k_bits < 18 else 18))
        self.last_height[li] = z
        self.state = [x, y, z, intensity, bits, cls, sar, ud, psid]
        _P10.pack_into(out, off, x, y, z, intensity, bits, cls, sar, ud, psid)


class GpsTime11V2:
    """GPSTIME11 version 2: the 8-byte GPS time of point formats 1, 3, 4, 5."""

    size = 8

    def __init__(self):
        self.m_multi = ArithmeticModel(GPS11_MULTI_TOTAL)
        self.m_0diff = ArithmeticModel(6)
        self.ic = IntegerDecompressor(32, 9)
        self.last = 0
        self.next = 0
        self.times = [0, 0, 0, 0]   # raw 64-bit patterns (unsigned)
        self.diffs = [0, 0, 0, 0]
        self.counters = [0, 0, 0, 0]

    def init(self, raw: bytes) -> None:
        (self.times[0],) = _U64.unpack(raw)

    def _read(self, dec: ArithmeticDecoder) -> None:
        last = self.last
        times = self.times
        diffs = self.diffs
        if diffs[last] == 0:
            multi = dec.decode_symbol(self.m_0diff)
            if multi == 1:
                d = self.ic.decompress(dec, 0, 0)
                diffs[last] = d
                times[last] = (times[last] + d) & MASK64
                self.counters[last] = 0
            elif multi == 2:
                nxt = self.next = (self.next + 1) & 3
                hi = self.ic.decompress(dec, _i32(times[last] >> 32), 8)
                times[nxt] = ((hi & MASK32) << 32) | dec.read_int()
                self.last = nxt
                diffs[nxt] = 0
                self.counters[nxt] = 0
            elif multi > 2:
                self.last = (last + multi - 2) & 3
                self._read(dec)
        else:
            multi = dec.decode_symbol(self.m_multi)
            if multi == 1:
                times[last] = (times[last] + self.ic.decompress(dec, diffs[last], 1)) & MASK64
                self.counters[last] = 0
            elif multi < GPS11_MULTI_UNCHANGED:
                if multi == 0:
                    d = self.ic.decompress(dec, 0, 7)
                    self.counters[last] += 1
                    if self.counters[last] > 3:
                        diffs[last] = d
                        self.counters[last] = 0
                elif multi < GPS_MULTI:
                    d = self.ic.decompress(dec, _i32(multi * diffs[last]), 2 if multi < 10 else 3)
                elif multi == GPS_MULTI:
                    d = self.ic.decompress(dec, _i32(GPS_MULTI * diffs[last]), 4)
                    self.counters[last] += 1
                    if self.counters[last] > 3:
                        diffs[last] = d
                        self.counters[last] = 0
                else:
                    multi = GPS_MULTI - multi
                    if multi > GPS_MULTI_MINUS:
                        d = self.ic.decompress(dec, _i32(multi * diffs[last]), 5)
                    else:
                        d = self.ic.decompress(dec, _i32(GPS_MULTI_MINUS * diffs[last]), 6)
                        self.counters[last] += 1
                        if self.counters[last] > 3:
                            diffs[last] = d
                            self.counters[last] = 0
                times[last] = (times[last] + d) & MASK64
            elif multi == GPS11_MULTI_CODE_FULL:
                nxt = self.next = (self.next + 1) & 3
                hi = self.ic.decompress(dec, _i32(times[last] >> 32), 8)
                times[nxt] = ((hi & MASK32) << 32) | dec.read_int()
                self.last = nxt
                diffs[nxt] = 0
                self.counters[nxt] = 0
            elif multi > GPS11_MULTI_CODE_FULL:
                self.last = (last + multi - GPS11_MULTI_CODE_FULL) & 3
                self._read(dec)

    def decode(self, dec: ArithmeticDecoder, out: bytearray, off: int) -> None:
        self._read(dec)
        _U64.pack_into(out, off, self.times[self.last])


class Rgb12V2:
    """RGB12 version 2: the 6-byte colour of point formats 2, 3, 5."""

    size = 6

    def __init__(self):
        self.models = _new_rgb_models()
        self.last = (0, 0, 0)

    def init(self, raw: bytes) -> None:
        self.last = _RGB.unpack(raw)

    def decode(self, dec: ArithmeticDecoder, out: bytearray, off: int) -> None:
        rgb = self.last = _decode_rgb(dec, self.models, self.last)
        _RGB.pack_into(out, off, *rgb)


class ByteV2:
    """BYTE version 2: per-byte delta coding of the extra bytes."""

    def __init__(self, size: int):
        self.size = size
        self.models = [ArithmeticModel(256) for _ in range(size)]
        self.last = bytearray(size)

    def init(self, raw: bytes) -> None:
        self.last[:] = raw

    def decode(self, dec: ArithmeticDecoder, out: bytearray, off: int) -> None:
        last = self.last
        decode = dec.decode_symbol
        for i, m in enumerate(self.models):
            last[i] = (last[i] + decode(m)) & 0xFF
        out[off:off + self.size] = last


# ---------------------------------------------------------------------------
# Version 3 layered items (compressor 3)
# ---------------------------------------------------------------------------

_P14 = struct.Struct("<IIiHBBBBhHQ")
_U32 = struct.Struct("<I")

GPS14_MULTI_CODE_FULL = GPS_MULTI - GPS_MULTI_MINUS + 1   # 511
GPS14_MULTI_TOTAL = GPS_MULTI - GPS_MULTI_MINUS + 5       # 515


def _layer_decoder(buf: bytes, pos: int, size: int):
    """Return (decoder or None, new_pos) for one compressed layer."""
    if size == 0:
        return None, pos
    end = pos + size
    if end > len(buf):
        raise LazError("compressed layer runs past the end of the chunk")
    return ArithmeticDecoder(bytes(buf[pos:end]) + _PAD), end


class _P14Context:
    """Per scanner-channel state of the POINT14 v3 decoder."""

    __slots__ = ("m_changed", "m_scanner", "m_nret", "m_rnum", "m_rnum_gps_same", "m_class",
                 "m_flags", "m_user", "m_gps_multi", "m_gps_0diff", "ic_dx", "ic_dy", "ic_z",
                 "ic_intensity", "ic_scan_angle", "ic_psid", "ic_gps", "med_x", "med_y",
                 "last_z", "last_intensity", "gps_last", "gps_next", "gps_times", "gps_diffs",
                 "gps_counters", "point", "gps_change")

    def __init__(self, point: list):
        # point = [x, y, z, intensity, returns, flags, cls, user, scan_angle, psid, gps]
        self.m_changed = [ArithmeticModel(128) for _ in range(8)]
        self.m_scanner = ArithmeticModel(3)
        self.m_nret = [None] * 16
        self.m_rnum = [None] * 16
        self.m_rnum_gps_same = ArithmeticModel(13)
        self.m_class = [None] * 64
        self.m_flags = [None] * 64
        self.m_user = [None] * 64
        self.m_gps_multi = ArithmeticModel(GPS14_MULTI_TOTAL)
        self.m_gps_0diff = ArithmeticModel(5)
        self.ic_dx = IntegerDecompressor(32, 2)
        self.ic_dy = IntegerDecompressor(32, 22)
        self.ic_z = IntegerDecompressor(32, 20)
        self.ic_intensity = IntegerDecompressor(16, 4)
        self.ic_scan_angle = IntegerDecompressor(16, 2)
        self.ic_psid = IntegerDecompressor(16, 1)
        self.ic_gps = IntegerDecompressor(32, 9)
        self.med_x = [StreamingMedian5() for _ in range(12)]
        self.med_y = [StreamingMedian5() for _ in range(12)]
        self.last_z = [point[2]] * 8
        self.last_intensity = [point[3]] * 8
        self.gps_last = 0
        self.gps_next = 0
        self.gps_times = [point[10], 0, 0, 0]
        self.gps_diffs = [0, 0, 0, 0]
        self.gps_counters = [0, 0, 0, 0]
        self.point = list(point)
        self.gps_change = False


class Point14V3:
    """POINT14 version 3: the 30-byte core of point formats 6-10.

    Nine layers: channel/returns/XY, Z, classification, flags, intensity,
    scan angle, user data, point source ID, GPS time. Up to four contexts,
    one per scanner channel.
    """

    size = 30
    LAYERS = ("channel_returns_xy", "z", "classification", "flags", "intensity",
              "scan_angle", "user_data", "point_source", "gps_time")

    def __init__(self):
        self.layer_sizes = [0] * 9
        self.decoders = [None] * 9
        self.contexts = [None] * 4
        self.current = 0

    def read_layer_sizes(self, buf: bytes, pos: int) -> int:
        self.layer_sizes = list(struct.unpack_from("<9I", buf, pos))
        return pos + 36

    def load_layers(self, buf: bytes, pos: int) -> int:
        for i, size in enumerate(self.layer_sizes):
            self.decoders[i], pos = _layer_decoder(buf, pos, size)
        if self.decoders[0] is None:
            # LASzip always initialises this decoder; an empty layer means the
            # chunk holds a single point
            self.decoders[0] = ArithmeticDecoder(_PAD)
        return pos

    def layers(self) -> list:
        return list(zip(self.LAYERS, self.layer_sizes, self.decoders))

    def init(self, raw: bytes) -> int:
        point = list(_P14.unpack(raw))
        self.contexts = [None] * 4
        self.current = (point[5] >> 4) & 3
        self.contexts[self.current] = _P14Context(point)
        return self.current

    def _read_gps_time(self, c: _P14Context) -> None:
        dec = self.decoders[8]
        last = c.gps_last
        times = c.gps_times
        diffs = c.gps_diffs
        counters = c.gps_counters
        if diffs[last] == 0:
            multi = dec.decode_symbol(c.m_gps_0diff)
            if multi == 0:
                d = c.ic_gps.decompress(dec, 0, 0)
                diffs[last] = d
                times[last] = (times[last] + d) & MASK64
                counters[last] = 0
            elif multi == 1:
                nxt = c.gps_next = (c.gps_next + 1) & 3
                hi = c.ic_gps.decompress(dec, _i32(times[last] >> 32), 8)
                times[nxt] = ((hi & MASK32) << 32) | dec.read_int()
                c.gps_last = nxt
                diffs[nxt] = 0
                counters[nxt] = 0
            else:
                c.gps_last = (last + multi - 1) & 3
                self._read_gps_time(c)
        else:
            multi = dec.decode_symbol(c.m_gps_multi)
            if multi == 1:
                times[last] = (times[last] + c.ic_gps.decompress(dec, diffs[last], 1)) & MASK64
                counters[last] = 0
            elif multi < GPS14_MULTI_CODE_FULL:
                if multi == 0:
                    d = c.ic_gps.decompress(dec, 0, 7)
                    counters[last] += 1
                    if counters[last] > 3:
                        diffs[last] = d
                        counters[last] = 0
                elif multi < GPS_MULTI:
                    d = c.ic_gps.decompress(dec, _i32(multi * diffs[last]), 2 if multi < 10 else 3)
                elif multi == GPS_MULTI:
                    d = c.ic_gps.decompress(dec, _i32(GPS_MULTI * diffs[last]), 4)
                    counters[last] += 1
                    if counters[last] > 3:
                        diffs[last] = d
                        counters[last] = 0
                else:
                    multi = GPS_MULTI - multi
                    if multi > GPS_MULTI_MINUS:
                        d = c.ic_gps.decompress(dec, _i32(multi * diffs[last]), 5)
                    else:
                        d = c.ic_gps.decompress(dec, _i32(GPS_MULTI_MINUS * diffs[last]), 6)
                        counters[last] += 1
                        if counters[last] > 3:
                            diffs[last] = d
                            counters[last] = 0
                times[last] = (times[last] + d) & MASK64
            elif multi == GPS14_MULTI_CODE_FULL:
                nxt = c.gps_next = (c.gps_next + 1) & 3
                hi = c.ic_gps.decompress(dec, _i32(times[last] >> 32), 8)
                times[nxt] = ((hi & MASK32) << 32) | dec.read_int()
                c.gps_last = nxt
                diffs[nxt] = 0
                counters[nxt] = 0
            else:
                c.gps_last = (last + multi - GPS14_MULTI_CODE_FULL) & 3
                self._read_gps_time(c)

    def decode(self, out: bytearray, off: int) -> int:
        c = self.contexts[self.current]
        p = c.point
        dec = self.decoders[0]
        last_r = p[4] & 15
        last_n = p[4] >> 4
        lpr = (1 if last_r == 1 else 0) + (2 if last_r >= last_n else 0) + (4 if c.gps_change else 0)
        changed = dec.decode_symbol(c.m_changed[lpr])
        if changed & 64:
            diff = dec.decode_symbol(c.m_scanner)
            channel = (self.current + diff + 1) & 3
            nc = self.contexts[channel]
            if nc is None:
                nc = self.contexts[channel] = _P14Context(p)
            self.current = channel
            c = nc
            p = c.point
            p[5] = (p[5] & 0xCF) | (channel << 4)
            last_r = p[4] & 15
            last_n = p[4] >> 4
        gps_change = 1 if changed & 16 else 0
        # number of returns
        if changed & 4:
            m = c.m_nret[last_n]
            if m is None:
                m = c.m_nret[last_n] = ArithmeticModel(16)
            n = dec.decode_symbol(m)
        else:
            n = last_n
        # return number
        rc = changed & 3
        if rc == 0:
            r = last_r
        elif rc == 1:
            r = (last_r + 1) & 15
        elif rc == 2:
            r = (last_r + 15) & 15
        elif gps_change:
            m = c.m_rnum[last_r]
            if m is None:
                m = c.m_rnum[last_r] = ArithmeticModel(16)
            r = dec.decode_symbol(m)
        else:
            r = (last_r + dec.decode_symbol(c.m_rnum_gps_same) + 2) & 15
        p[4] = r | (n << 4)
        mi = NUMBER_RETURN_MAP_6CTX[n][r]
        li = NUMBER_RETURN_LEVEL_8CTX[n][r]
        cpr = (2 if r == 1 else 0) + (1 if r >= n else 0)
        n1 = 1 if n == 1 else 0
        idx = (mi << 1) | gps_change
        # X and Y
        med = c.med_x[idx]
        diff = c.ic_dx.decompress(dec, med.v[2], n1)
        p[0] = (p[0] + diff) & MASK32
        med.add(diff)
        med = c.med_y[idx]
        k_bits = c.ic_dx.k
        diff = c.ic_dy.decompress(dec, med.v[2], n1 + ((k_bits & ~1) if k_bits < 20 else 20))
        p[1] = (p[1] + diff) & MASK32
        med.add(diff)
        decoders = self.decoders
        # Z
        d = decoders[1]
        if d is not None:
            k_bits = (c.ic_dx.k + c.ic_dy.k) >> 1
            z = c.ic_z.decompress(d, c.last_z[li], n1 + ((k_bits & ~1) if k_bits < 18 else 18))
            p[2] = z
            c.last_z[li] = z
        # classification
        d = decoders[2]
        if d is not None:
            ccc = ((p[6] & 0x1F) << 1) + (1 if cpr == 3 else 0)
            m = c.m_class[ccc]
            if m is None:
                m = c.m_class[ccc] = ArithmeticModel(256)
            p[6] = d.decode_symbol(m)
        # flags (edge, scan direction, classification flags; channel kept)
        d = decoders[3]
        if d is not None:
            f = p[5]
            last_flags = ((f >> 7) << 5) | (((f >> 6) & 1) << 4) | (f & 0x0F)
            m = c.m_flags[last_flags]
            if m is None:
                m = c.m_flags[last_flags] = ArithmeticModel(64)
            flags = d.decode_symbol(m)
            p[5] = (((flags >> 5) & 1) << 7) | (((flags >> 4) & 1) << 6) | (f & 0x30) | (flags & 0x0F)
        # intensity
        d = decoders[4]
        if d is not None:
            ii = (cpr << 1) | gps_change
            intensity = c.ic_intensity.decompress(d, c.last_intensity[ii], cpr)
            c.last_intensity[ii] = intensity
            p[3] = intensity
        # scan angle
        d = decoders[5]
        if d is not None and changed & 8:
            v = c.ic_scan_angle.decompress(d, p[8], gps_change)
            p[8] = v - 0x10000 if v >= 0x8000 else v
        # user data
        d = decoders[6]
        if d is not None:
            ui = p[7] >> 2
            m = c.m_user[ui]
            if m is None:
                m = c.m_user[ui] = ArithmeticModel(256)
            p[7] = d.decode_symbol(m)
        # point source ID
        d = decoders[7]
        if d is not None and changed & 32:
            p[9] = c.ic_psid.decompress(d, p[9], 0)
        # GPS time
        if decoders[8] is not None and gps_change:
            self._read_gps_time(c)
            p[10] = c.gps_times[c.gps_last]
        c.gps_change = bool(gps_change)
        _P14.pack_into(out, off, *p)
        return self.current


class Rgb14V3:
    """RGB14 version 3: one layer, per-context RGB12-style predictor."""

    size = 6

    def __init__(self):
        self.layer_size = 0
        self.dec = None
        self.models = [None] * 4
        self.last = [None] * 4
        self.current = 0

    def read_layer_sizes(self, buf: bytes, pos: int) -> int:
        (self.layer_size,) = _U32.unpack_from(buf, pos)
        return pos + 4

    def load_layers(self, buf: bytes, pos: int) -> int:
        self.dec, pos = _layer_decoder(buf, pos, self.layer_size)
        return pos

    def layers(self) -> list:
        return [("rgb", self.layer_size, self.dec)]

    def init(self, raw: bytes, context: int) -> None:
        self.models = [None] * 4
        self.last = [None] * 4
        self.models[context] = _new_rgb_models()
        self.last[context] = _RGB.unpack(raw)
        self.current = context

    def decode(self, out: bytearray, off: int, context: int) -> None:
        # LASzip v3 quirk: on a switch to an already-used context, the point
        # is still predicted from (and stored into) the previous context's
        # last value; only a newly initialised context switches immediately.
        li = self.current
        if context != li:
            self.current = context
            if self.models[context] is None:
                self.models[context] = _new_rgb_models()
                self.last[context] = self.last[li]
                li = context
        if self.dec is not None:
            self.last[li] = _decode_rgb(self.dec, self.models[context], self.last[li])
        _RGB.pack_into(out, off, *self.last[li])


class RgbNir14V3:
    """RGBNIR14 version 3: RGB layer plus NIR layer, shared contexts."""

    size = 8

    def __init__(self):
        self.size_rgb = 0
        self.size_nir = 0
        self.dec_rgb = None
        self.dec_nir = None
        self.models = [None] * 4
        self.last = [None] * 4  # (r, g, b, nir)
        self.current = 0

    def read_layer_sizes(self, buf: bytes, pos: int) -> int:
        self.size_rgb, self.size_nir = struct.unpack_from("<II", buf, pos)
        return pos + 8

    def load_layers(self, buf: bytes, pos: int) -> int:
        self.dec_rgb, pos = _layer_decoder(buf, pos, self.size_rgb)
        self.dec_nir, pos = _layer_decoder(buf, pos, self.size_nir)
        return pos

    def layers(self) -> list:
        return [("rgb", self.size_rgb, self.dec_rgb), ("nir", self.size_nir, self.dec_nir)]

    @staticmethod
    def _new_models() -> tuple:
        return (_new_rgb_models(),
                [ArithmeticModel(4), ArithmeticModel(256), ArithmeticModel(256)])

    def init(self, raw: bytes, context: int) -> None:
        self.models = [None] * 4
        self.last = [None] * 4
        self.models[context] = self._new_models()
        self.last[context] = struct.unpack("<HHHH", raw)
        self.current = context

    def decode(self, out: bytearray, off: int, context: int) -> None:
        li = self.current
        if context != li:
            self.current = context
            if self.models[context] is None:
                self.models[context] = self._new_models()
                self.last[context] = self.last[li]
                li = context
        m_rgb, m_nir = self.models[context]
        r, g, b, nir = self.last[li]
        if self.dec_rgb is not None:
            r, g, b = _decode_rgb(self.dec_rgb, m_rgb, (r, g, b))
        if self.dec_nir is not None:
            nir = _decode_nir(self.dec_nir, m_nir, nir)
        self.last[li] = (r, g, b, nir)
        struct.pack_into("<HHHH", out, off, r, g, b, nir)


class Byte14V3:
    """BYTE14 version 3: one layer per extra byte, per-context delta coding."""

    def __init__(self, size: int):
        self.size = size
        self.layer_sizes = [0] * size
        self.decs = [None] * size
        self.models = [None] * 4
        self.last = [None] * 4
        self.current = 0

    def read_layer_sizes(self, buf: bytes, pos: int) -> int:
        self.layer_sizes = list(struct.unpack_from(f"<{self.size}I", buf, pos))
        return pos + 4 * self.size

    def load_layers(self, buf: bytes, pos: int) -> int:
        for i, size in enumerate(self.layer_sizes):
            self.decs[i], pos = _layer_decoder(buf, pos, size)
        return pos

    def layers(self) -> list:
        return [(f"byte{i}", size, d) for i, (size, d) in enumerate(zip(self.layer_sizes, self.decs))]

    def init(self, raw: bytes, context: int) -> None:
        self.models = [None] * 4
        self.last = [None] * 4
        self.models[context] = [ArithmeticModel(256) for _ in range(self.size)]
        self.last[context] = bytearray(raw)
        self.current = context

    def decode(self, out: bytearray, off: int, context: int) -> None:
        li = self.current
        if context != li:
            self.current = context
            if self.models[context] is None:
                self.models[context] = [ArithmeticModel(256) for _ in range(self.size)]
                self.last[context] = bytearray(self.last[li])
                li = context
        last = self.last[li]
        models = self.models[context]
        for i, d in enumerate(self.decs):
            if d is not None:
                last[i] = (last[i] + d.decode_symbol(models[i])) & 0xFF
        out[off:off + self.size] = last


# ---------------------------------------------------------------------------
# Item setup and chunk decoding
# ---------------------------------------------------------------------------

def _check_items(hdr: dict) -> tuple:
    """Validate the LASzip item list; return (compressor, items)."""
    lz = hdr["laszip"]
    if lz is None:
        raise LazError("file is not LASzip-compressed")
    if lz["coder"] != 0:
        raise LazError(f"unsupported LASzip coder {lz['coder']} (only 0 = arithmetic)")
    compressor = lz["compressor"]
    items = lz["items"]
    if compressor not in (COMPRESSOR_POINTWISE, COMPRESSOR_POINTWISE_CHUNKED, COMPRESSOR_LAYERED_CHUNKED):
        raise LazError(f"unsupported LASzip compressor {compressor}")
    fmt = hdr["point_format"]
    if fmt in (4, 5, 9, 10):
        raise LazError(f"point format {fmt} carries wave packets, which this decoder does not support")
    for it in items:
        t, v, name = it["type"], it["version"], it["name"]
        if t in (ITEM_WAVEPACKET13, ITEM_WAVEPACKET14):
            raise LazError(f"item {name} (wave packets) is not supported")
        if t in ITEM_FIXED_SIZES and it["size"] != ITEM_FIXED_SIZES[t]:
            raise LazError(f"item {name} has size {it['size']}, expected {ITEM_FIXED_SIZES[t]}")
        if compressor == COMPRESSOR_LAYERED_CHUNKED:
            if t not in (ITEM_POINT14, ITEM_RGB14, ITEM_RGBNIR14, ITEM_BYTE14):
                raise LazError(f"item {name} cannot be used with the layered chunked compressor")
            if v != 3:
                raise LazError(f"item {name} version {v} is not supported (only version 3)")
        else:
            if t not in (ITEM_POINT10, ITEM_GPSTIME11, ITEM_RGB12, ITEM_BYTE):
                raise LazError(f"item {name} cannot be used with the point-wise compressor")
            if v != 2:
                raise LazError(f"item {name} version {v} is not supported (only version 2; "
                               "version 1 is the pre-2012 LASzip 1.x format)")
    if compressor == COMPRESSOR_LAYERED_CHUNKED and (not items or items[0]["type"] != ITEM_POINT14):
        raise LazError("layered chunked compression needs POINT14 as the first item")
    if compressor != COMPRESSOR_LAYERED_CHUNKED and (not items or items[0]["type"] != ITEM_POINT10):
        raise LazError("point-wise compression needs POINT10 as the first item")
    total = sum(it["size"] for it in items)
    if total != hdr["point_record_length"]:
        raise LazError(f"LASzip items cover {total} bytes but the point record length is "
                       f"{hdr['point_record_length']}")
    return compressor, items


def _make_v2_items(items: list) -> list:
    out = []
    for it in items:
        t = it["type"]
        if t == ITEM_POINT10:
            out.append(Point10V2())
        elif t == ITEM_GPSTIME11:
            out.append(GpsTime11V2())
        elif t == ITEM_RGB12:
            out.append(Rgb12V2())
        else:
            out.append(ByteV2(it["size"]))
    return out


def _make_v3_items(items: list) -> list:
    out = []
    for it in items:
        t = it["type"]
        if t == ITEM_POINT14:
            out.append(Point14V3())
        elif t == ITEM_RGB14:
            out.append(Rgb14V3())
        elif t == ITEM_RGBNIR14:
            out.append(RgbNir14V3())
        else:
            out.append(Byte14V3(it["size"]))
    return out


def decode_pointwise_chunk(buf: bytes, items: list, record_length: int, n_points: int,
                           pos: int = 0) -> tuple:
    """Decode one point-wise (compressor 1/2, version 2 items) chunk.

    `buf` holds the chunk bytes starting at `pos`, followed by >= 4 bytes of
    zero padding. Returns (records, end_pos) where end_pos is the position
    just after the bytes the arithmetic decoder consumed.
    """
    out = bytearray(record_length * n_points)
    if n_points == 0:
        return out, pos
    decoders = _make_v2_items(items)
    first = bytes(buf[pos:pos + record_length])
    if len(first) < record_length:
        raise LazError("chunk is shorter than one raw point")
    out[0:record_length] = first
    offsets = []
    o = 0
    for d in decoders:
        d.init(first[o:o + d.size])
        offsets.append(o)
        o += d.size
    pos += record_length
    # the arithmetic stream starts right after the raw first point (the
    # encoder writes its 4 init bytes even when the chunk has one point)
    dec = ArithmeticDecoder(buf, pos)
    if len(decoders) == 1:
        d0 = decoders[0].decode
        off = record_length
        for _ in range(1, n_points):
            d0(dec, out, off)
            off += record_length
    else:
        pairs = [(d.decode, o) for d, o in zip(decoders, offsets)]
        off = record_length
        for _ in range(1, n_points):
            for decode, o in pairs:
                decode(dec, out, off + o)
            off += record_length
    return out, dec.pos


def decode_layered_chunk(buf: bytes, items: list, record_length: int, n_points,
                         pos: int = 0) -> tuple:
    """Decode one layered (compressor 3, version 3 items) chunk.

    Chunk layout: raw first point, u32 point count, the u32 byte size of
    every layer of every item, then the layers themselves. If n_points is
    None, the stored point count is used. When the whole chunk is decoded,
    every layer decoder must have consumed exactly its layer (LASzip's
    encoder flushes so the decoder stays in sync); anything else means a
    corrupt chunk or a decoder bug and raises LazError.
    Returns (records, end_pos, stored_count).
    """
    decoders = _make_v3_items(items)
    first = bytes(buf[pos:pos + record_length])
    if len(first) < record_length:
        raise LazError("chunk is shorter than one raw point")
    pos += record_length
    (count,) = _U32.unpack_from(buf, pos)
    pos += 4
    if n_points is None:
        n_points = count
    if n_points > count:
        raise LazError(f"chunk stores {count} points but {n_points} were expected")
    for d in decoders:
        pos = d.read_layer_sizes(buf, pos)
    for d in decoders:
        pos = d.load_layers(buf, pos)
    out = bytearray(record_length * n_points)
    if n_points == 0:
        return out, pos, count
    out[0:record_length] = first
    point14 = decoders[0]
    context = point14.init(first[0:30])
    others = []
    o = 30
    for d in decoders[1:]:
        d.init(first[o:o + d.size], context)
        others.append((d.decode, o))
        o += d.size
    p14 = point14.decode
    off = record_length
    if not others:
        for _ in range(1, n_points):
            p14(out, off)
            off += record_length
    else:
        for _ in range(1, n_points):
            context = p14(out, off)
            for dec_fn, o in others:
                dec_fn(out, off + o, context)
            off += record_length
    if n_points == count and count > 1:
        for d in decoders:
            for name, size, layer_dec in d.layers():
                if size and layer_dec is not None and layer_dec.pos != size:
                    raise LazError(f"{type(d).__name__} layer {name}: decoder consumed "
                                   f"{layer_dec.pos} of {size} bytes (corrupt chunk?)")
    return out, pos, count


# ---------------------------------------------------------------------------
# Chunk table
# ---------------------------------------------------------------------------

def read_chunk_table(fh, hdr: dict) -> dict:
    """Locate and decode the chunk table.

    Returns a dict with keys: chunks_start (first chunk byte offset),
    table_offset (or None), entries (list of (point_count or None,
    byte_count)) or None when the file has no usable chunk table.
    """
    lz = hdr["laszip"]
    data_start = hdr["offset_to_point_data"]
    info = {"chunks_start": data_start, "table_offset": None, "entries": None, "note": ""}
    if lz["compressor"] == COMPRESSOR_POINTWISE:
        info["note"] = "point-wise compressor: one chunk, no chunk table"
        return info
    fh.seek(data_start)
    raw = fh.read(8)
    if len(raw) < 8:
        raise LazError("file ends before the chunk table offset")
    (table_offset,) = struct.unpack("<q", raw)
    chunks_start = data_start + 8
    info["chunks_start"] = chunks_start
    if table_offset == -1:
        # written by a streaming compressor: the offset is the last 8 bytes
        fh.seek(hdr["file_size"] - 8)
        (table_offset,) = struct.unpack("<q", fh.read(8))
        info["note"] = "chunk table offset read from the end of the file"
    if table_offset + 8 == chunks_start or table_offset <= data_start:
        info["note"] = "compressor did not write a chunk table"
        return info
    variable = lz["variable_chunks"]
    try:
        fh.seek(table_offset)
        head = fh.read(8)
        if len(head) < 8:
            raise LazError("chunk table header is truncated")
        version, number_chunks = struct.unpack("<II", head)
        if version != 0:
            raise LazError(f"unknown chunk table version {version}")
        body = fh.read(16 * number_chunks + 64) + _PAD
        entries = []
        if number_chunks:
            dec = ArithmeticDecoder(body, 0)
            ic = IntegerDecompressor(32, 2)
            prev_count = 0
            prev_bytes = 0
            for _ in range(number_chunks):
                count = None
                if variable:
                    prev_count = ic.decompress(dec, prev_count, 0)
                    count = prev_count & MASK32
                prev_bytes = ic.decompress(dec, prev_bytes, 1)
                if prev_bytes <= 0:
                    raise LazError("chunk table has a non-positive chunk byte size")
                entries.append((count, prev_bytes))
        info["table_offset"] = table_offset
        info["entries"] = entries
    except (LazError, struct.error, IndexError) as exc:
        info["note"] = f"unusable chunk table ({exc})"
        info["entries"] = None
    return info


def _chunk_plan(fh, hdr: dict) -> tuple:
    """Return (compressor, items, table_info)."""
    compressor, items = _check_items(hdr)
    table = read_chunk_table(fh, hdr)
    if table["entries"] is None and compressor == COMPRESSOR_POINTWISE_CHUNKED \
            and hdr["laszip"]["variable_chunks"]:
        raise LazError("variable-size point-wise chunks need a chunk table, which is missing "
                       f"or unusable ({table['note']})")
    return compressor, items, table


def _end_of_point_region(hdr: dict, table: dict) -> int:
    if table.get("table_offset"):
        return table["table_offset"]
    if hdr["number_of_evlrs"] and hdr["start_of_first_evlr"] > hdr["offset_to_point_data"]:
        return hdr["start_of_first_evlr"]
    return hdr["file_size"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def iter_chunks(path: str, max_points=None, header: dict = None):
    """Yield (chunk_index, n_points, record_bytes) for each chunk of a file.

    record_bytes holds n_points uncompressed LAS point records exactly as in
    the equivalent .las file. Works for uncompressed LAS too (records are
    then yielded in blocks of 50000). Stops after max_points points.
    """
    hdr = header if header is not None else read_header(path)
    total = hdr["point_count"]
    if max_points is not None:
        total = min(total, max_points)
    rlen = hdr["point_record_length"]
    with open(path, "rb") as fh:
        if not hdr["compressed"]:
            fh.seek(hdr["offset_to_point_data"])
            done = 0
            index = 0
            while done < total:
                n = min(50000, total - done)
                data = fh.read(n * rlen)
                if len(data) < n * rlen:
                    raise LazError("LAS file is truncated")
                yield index, n, data
                done += n
                index += 1
            return
        state = {"chunk": 0}
        try:
            yield from _iter_compressed_chunks(fh, hdr, total, max_points, state)
        except (IndexError, struct.error, ZeroDivisionError) as exc:
            # a desynchronised arithmetic decoder runs off its buffer
            raise LazError(f"chunk {state['chunk']} is corrupt "
                           f"({type(exc).__name__}: {exc})") from exc


def _iter_compressed_chunks(fh, hdr: dict, total: int, max_points, state: dict):
    """Generator behind iter_chunks() for LASzip-compressed files."""
    rlen = hdr["point_record_length"]
    compressor, items, table = _chunk_plan(fh, hdr)
    lz = hdr["laszip"]
    if compressor == COMPRESSOR_POINTWISE:
        chunk_size = None
    else:
        chunk_size = None if lz["variable_chunks"] else lz["chunk_size"]
    entries = table["entries"] or []
    done = 0
    pos = table["chunks_start"]
    for index, (count, nbytes) in enumerate(entries):
        if done >= total:
            return
        state["chunk"] = index
        fh.seek(pos)
        buf = fh.read(nbytes) + _PAD
        if len(buf) < nbytes + len(_PAD):
            raise LazError(f"chunk {index} is truncated")
        if compressor == COMPRESSOR_LAYERED_CHUNKED:
            (stored,) = _U32.unpack_from(buf, rlen)
            if count is not None and count != stored:
                raise LazError(f"chunk {index} stores {stored} points but the chunk "
                               f"table says {count}")
            if chunk_size is not None and stored > chunk_size:
                raise LazError(f"chunk {index} stores {stored} points, more than the "
                               f"chunk size {chunk_size}")
            n = min(stored, total - done)
            records, _, _ = decode_layered_chunk(buf, items, rlen, n)
        else:
            want = count if count is not None else chunk_size
            n = min(want, total - done)
            records, end = decode_pointwise_chunk(buf, items, rlen, n)
            complete = n == want or (index == len(entries) - 1 and max_points is None)
            if complete and end != nbytes:
                raise LazError(f"chunk {index}: decoder consumed {end} bytes but the chunk "
                               f"table says {nbytes} (corrupt chunk or wrong point count?)")
        yield index, n, records
        done += n
        pos += nbytes
    if done >= total:
        return
    if entries and compressor == COMPRESSOR_POINTWISE_CHUNKED and chunk_size is None:
        raise LazError(f"chunk table covers {done} points but the header declares {total}")
    # No (or an incomplete) chunk table: decode the remaining chunks back to
    # back, as LASzip does; each chunk starts where the previous one ended.
    index = len(entries)
    end_region = _end_of_point_region(hdr, table)
    if end_region <= pos:
        end_region = hdr["file_size"]
    fh.seek(pos)
    buf = fh.read(end_region - pos) + _PAD
    limit = len(buf) - len(_PAD)
    pos = 0
    while done < total:
        state["chunk"] = index
        if compressor == COMPRESSOR_LAYERED_CHUNKED:
            (stored,) = _U32.unpack_from(buf, pos + rlen)
            if chunk_size is not None and stored > chunk_size:
                raise LazError(f"chunk {index} stores {stored} points, more than the "
                               f"chunk size {chunk_size}")
            n = min(stored, total - done)
            records, pos, _ = decode_layered_chunk(buf, items, rlen, n, pos)
        elif compressor == COMPRESSOR_POINTWISE:
            n = total - done
            records, pos = decode_pointwise_chunk(buf, items, rlen, n, pos)
        else:
            n = min(chunk_size, total - done)
            records, pos = decode_pointwise_chunk(buf, items, rlen, n, pos)
        if n == 0:
            raise LazError(f"chunk {index} is empty while points remain")
        if pos > limit:
            raise LazError(f"chunk {index} runs past the end of the point data")
        yield index, n, records
        done += n
        index += 1


def decode_points(path: str, max_points=None) -> tuple:
    """Decode a LAZ (or LAS) file into uncompressed LAS point records.

    Returns (header_dict, point_record_bytes); point_record_bytes is the
    concatenation of the point records exactly as they appear in the
    equivalent uncompressed .las file.
    """
    hdr = read_header(path)
    parts = [records for _, _, records in iter_chunks(path, max_points, header=hdr)]
    return hdr, b"".join(parts)


def write_las(src_path: str, dst_path: str, max_points=None) -> dict:
    """Decompress src_path into an uncompressed LAS file at dst_path."""
    hdr = read_header(src_path)
    with open(src_path, "rb") as fh:
        prefix = bytearray(fh.read(hdr["offset_to_point_data"]))
        evlr_bytes = b""
        if hdr["number_of_evlrs"] and hdr["evlrs"]:
            fh.seek(hdr["start_of_first_evlr"])
            evlr_bytes = fh.read(hdr["end_of_evlrs"] - hdr["start_of_first_evlr"])
    header_bytes = bytearray(prefix[:hdr["header_size"]])
    vlr_parts = []
    kept = 0
    for vlr in hdr["vlrs"]:
        if vlr["user_id"] == LASZIP_USER_ID and vlr["record_id"] == LASZIP_RECORD_ID:
            continue
        vlr_parts.append(bytes(prefix[vlr["header_offset"]:vlr["data_offset"] + vlr["length"]]))
        kept += 1
    padding = bytes(prefix[hdr["end_of_vlrs"]:])
    offset_to_points = hdr["header_size"] + sum(len(p) for p in vlr_parts) + len(padding)
    n_points = hdr["point_count"] if max_points is None else min(hdr["point_count"], max_points)
    struct.pack_into("<II", header_bytes, 96, offset_to_points, kept)
    header_bytes[104] = hdr["point_format"]
    if max_points is not None:
        # only the point counts change; bounds and per-return counts still
        # describe the whole input
        if hdr["legacy_point_count"] and n_points <= MASK32:
            struct.pack_into("<I", header_bytes, 107, n_points)
        if hdr["point_count_64"] is not None:
            struct.pack_into("<Q", header_bytes, 247, n_points)
    if hdr["point_count_64"] is not None:
        start_evlr = offset_to_points + n_points * hdr["point_record_length"] if evlr_bytes else 0
        struct.pack_into("<Q", header_bytes, 235, start_evlr)
    t0 = time.perf_counter()
    written = 0
    tmp_path = f"{dst_path}.part"
    try:
        with open(tmp_path, "wb") as out:
            out.write(header_bytes)
            for part in vlr_parts:
                out.write(part)
            out.write(padding)
            for _, n, records in iter_chunks(src_path, max_points, header=hdr):
                out.write(records)
                written += n
            out.write(evlr_bytes)
        os.replace(tmp_path, dst_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    elapsed = time.perf_counter() - t0
    return {"points": written, "seconds": elapsed}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_info(args) -> int:
    hdr = read_header(args.path)
    print(f"file: {args.path} ({hdr['file_size']} bytes)")
    print(f"LAS {hdr['version']}  point format {hdr['point_format']} (raw byte {hdr['point_format_raw']})"
          f"  record length {hdr['point_record_length']}"
          f"  extra bytes {hdr['extra_bytes_per_point']}")
    print(f"points: {hdr['point_count']} (legacy field {hdr['legacy_point_count']},"
          f" 64-bit field {hdr['point_count_64']})")
    print(f"software: {hdr['generating_software']!r}  system: {hdr['system_identifier']!r}")
    print(f"scale: {hdr['scale']}  offset: {hdr['offset']}")
    print(f"min: {hdr['min']}  max: {hdr['max']}")
    print(f"offset to point data: {hdr['offset_to_point_data']}  header size: {hdr['header_size']}")
    for vlr in hdr["vlrs"]:
        print(f"VLR {vlr['user_id']!r} {vlr['record_id']} length {vlr['length']} {vlr['description']!r}")
    for evlr in hdr["evlrs"]:
        print(f"EVLR {evlr['user_id']!r} {evlr['record_id']} length {evlr['length']}")
    lz = hdr["laszip"]
    if lz is None:
        print("not LASzip-compressed")
        return 0
    chunk = "variable" if lz["variable_chunks"] else lz["chunk_size"]
    print(f"LASzip {lz['version']} compressor {lz['compressor']} ({lz['compressor_name']})"
          f" coder {lz['coder']} chunk size {chunk}")
    for it in lz["items"]:
        print(f"  item {it['name']} size {it['size']} version {it['version']}")
    try:
        _check_items(hdr)
        supported = "yes"
    except LazError as exc:
        supported = f"no: {exc}"
    print(f"decodable by this tool: {supported}")
    with open(args.path, "rb") as fh:
        table = read_chunk_table(fh, hdr)
    if table["entries"] is not None:
        counts = [c for c, _ in table["entries"]]
        sizes = [b for _, b in table["entries"]]
        msg = f"chunk table at {table['table_offset']}: {len(sizes)} chunks, {sum(sizes)} bytes"
        if counts and counts[0] is not None:
            msg += f", {sum(counts)} points (min {min(counts)}, max {max(counts)} per chunk)"
        print(msg)
    if table["note"]:
        print(f"note: {table['note']}")
    return 0


def _cmd_decode(args) -> int:
    stats = write_las(args.src, args.dst, args.max_points)
    rate = stats["points"] / stats["seconds"] if stats["seconds"] > 0 else float("inf")
    print(f"wrote {args.dst}: {stats['points']} points in {stats['seconds']:.2f} s"
          f" ({rate:,.0f} points/s)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pure-Python LAZ (LASzip) decoder")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_info = sub.add_parser("info", help="print header, VLRs, LASzip items and chunk table")
    p_info.add_argument("path")
    p_dec = sub.add_parser("decode", help="decompress a .laz into an uncompressed .las")
    p_dec.add_argument("src")
    p_dec.add_argument("dst")
    p_dec.add_argument("--max-points", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "info":
            return _cmd_info(args)
        return _cmd_decode(args)
    except LazError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
