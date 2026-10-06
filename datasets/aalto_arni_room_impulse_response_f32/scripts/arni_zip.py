#!/usr/bin/env python3
"""Dependency-free helpers for the Arni impulse-response recipe.

The Zenodo record ships its 132,037 WAV impulse responses inside six large
ZIP archives (4.3-9.7 GB).  The recipe never downloads a whole archive: it
fetches each archive's end-of-central-directory tail, then the exact central
directory, then exact byte ranges for the selected members.  This module holds
the pure parsing logic shared by discover.sh, download.sh, build.sh and
verify.sh:

* classic EOCD and ZIP64 EOCD locator/record parsing;
* central-directory parsing including the ZIP64 extended-information extra
  field (header id 0x0001) for sizes and local-header offsets above 4 GiB;
* local-header parsing that uses the local header's *own* name/extra lengths,
  raw DEFLATE inflation, exact-boundary and CRC-32 checks;
* RIFF/WAVE parsing that requires mono 44.1 kHz IEEE float32 and returns the
  `data` chunk's little-endian float32 sample block;
* the deterministic member-selection rule.

Network I/O is done by curl in the shell scripts; Python only parses files.
"""
from __future__ import annotations

import math
import operator
import re
import struct
import sys
import zlib
from dataclasses import dataclass

EOCD_SIG = b"PK\x05\x06"
ZIP64_LOCATOR_SIG = b"PK\x06\x07"
ZIP64_EOCD_SIG = b"PK\x06\x06"
CD_SIG = b"PK\x01\x02"
LOCAL_SIG = b"PK\x03\x04"

# Expected WAV layout of every Arni impulse response.
WAV_FORMAT_IEEE_FLOAT = 3
WAV_CHANNELS = 1
WAV_RATE = 44100
WAV_BYTE_RATE = 176400
WAV_BLOCK_ALIGN = 4
WAV_BITS = 32
WAV_DATA_BYTES = 423360
WAV_VALUES = WAV_DATA_BYTES // 4  # 105,840 samples = 2.4 s
WAV_MEMBER_BYTES = 423440

NAME_RE = re.compile(
    r"(?:^|/)IR_numClosed_(\d+)_numComb_(\d+)_mic_(\d+)_sweep_(\d+)\.wav$"
)
NUM_CLOSED_RANGE = range(0, 56)
MICS = (1, 2, 3, 4, 5)
SELECTED_SWEEP = 1
# Out-of-sequence special configuration block (see select_members).
EXCLUDED_COMBOS = range(2, 32)
# Absorption levels whose upstream receiver files repeat one response under
# several mic labels (mics 1-3 identical, mics 4-5 usually identical) in every
# probed regular configuration from the start of the block (see README):
# numClosed 11 (1042, 1043, 1060, 1100, 1120, 1141), 27 (2642, 2643, 2660,
# 2700, 2720) and 35 (3442, 3443, 3470, 3500, 3520).
EXCLUDED_LEVELS = (11, 27, 35)

# Receiver-distinctness check: zero-lag Pearson correlation of the five
# receivers of one configuration over sample indices [1500, 17884) (direct
# sound and early decay).  Correct configurations measure <= ~0.09; repeated
# responses filed under different receiver labels measure ~0.9996-0.9999.
DISTINCT_WINDOW = (1500, 17884)
DISTINCT_MAX_ABS_R = 0.5

# Metadata-only guard against int16-quantized members written as float32:
# of 132,037 members only four (numClosed 16, mic 5, sweep 1, numComb 1542,
# 1543, 1544, 1594) DEFLATE to 12.8-13.8 KB; every other member is at least
# 342,676 B.  Those four hold 100% 2^-15-lattice values (192 distinct codes).
MIN_COMPRESSED_BYTES = 200_000

# Float-lattice / degeneracy check (fatal): fraction of values with
# x * 32768 integral must be < 0.01 and the number of distinct float32 bit
# patterns must be >= 50,000.  Genuine samples measure 0% and >= 105,039.
INT16_LATTICE_SCALE = 32768
MAX_INT16_LATTICE_FRACTION = 0.01
MIN_DISTINCT_BIT_PATTERNS = 50_000


class ZipFormatError(ValueError):
    pass


@dataclass(frozen=True)
class CentralDirectoryLocation:
    cd_offset: int
    cd_size: int
    entries: int
    zip64: bool
    eocd_offset: int  # absolute offset of the classic EOCD record


@dataclass(frozen=True)
class Member:
    name: str
    flags: int
    method: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    local_header_offset: int
    cd_name_len: int
    cd_extra_len: int


def parse_final_http_status(headers_text: str) -> tuple[int, tuple[int, int, int] | None]:
    """Return (status, (start, end, total)) of the last response in a curl -D dump."""
    responses = re.split(r"(?=^HTTP/)", headers_text, flags=re.MULTILINE)
    final = ""
    for part in reversed(responses):
        if part.strip() and not re.match(r"HTTP/\S+\s+200 Connection established", part):
            final = part
            break
    status_match = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    status = int(status_match.group(1)) if status_match else 0
    range_match = re.search(
        r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$",
        final,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    content_range = tuple(int(x) for x in range_match.groups()) if range_match else None
    return status, content_range  # type: ignore[return-value]


def locate_central_directory(tail: bytes, tail_start: int, archive_size: int) -> CentralDirectoryLocation:
    """Find the central directory from an archive tail (classic or ZIP64)."""
    if tail_start + len(tail) != archive_size:
        raise ZipFormatError("tail does not end at the archive boundary")
    eocd_rel = tail.rfind(EOCD_SIG)
    while eocd_rel >= 0:
        if eocd_rel + 22 <= len(tail):
            comment_len = struct.unpack_from("<H", tail, eocd_rel + 20)[0]
            if eocd_rel + 22 + comment_len == len(tail):
                break
        eocd_rel = tail.rfind(EOCD_SIG, 0, eocd_rel)
    if eocd_rel < 0:
        raise ZipFormatError("classic EOCD record not found in tail")
    (_, disk, cd_disk, disk_entries, total_entries, cd_size, cd_offset, _comment_len) = struct.unpack_from(
        "<4s4H2IH", tail, eocd_rel
    )
    eocd_abs = tail_start + eocd_rel
    needs_zip64 = 0xFFFF in (disk, cd_disk, disk_entries, total_entries) or 0xFFFFFFFF in (cd_size, cd_offset)
    locator_rel = eocd_rel - 20
    has_locator = locator_rel >= 0 and tail[locator_rel : locator_rel + 4] == ZIP64_LOCATOR_SIG
    if has_locator:
        _, loc_disk, z64_eocd_abs, total_disks = struct.unpack_from("<4sIQI", tail, locator_rel)
        if loc_disk != 0 or total_disks != 1:
            raise ZipFormatError("multi-disk ZIP64 archive is unsupported")
        z64_rel = z64_eocd_abs - tail_start
        if z64_rel < 0 or z64_rel + 56 > locator_rel:
            raise ZipFormatError("ZIP64 EOCD record lies outside the fetched tail")
        if tail[z64_rel : z64_rel + 4] != ZIP64_EOCD_SIG:
            raise ZipFormatError("bad ZIP64 EOCD record signature")
        (_, record_size, _made, _need, z_disk, z_cd_disk, z_disk_entries, z_total, z_cd_size, z_cd_offset) = (
            struct.unpack_from("<4sQ2H2I4Q", tail, z64_rel)
        )
        if z_disk != 0 or z_cd_disk != 0 or z_disk_entries != z_total:
            raise ZipFormatError("multi-disk ZIP64 archive is unsupported")
        if z64_rel + 12 + record_size != locator_rel:
            raise ZipFormatError("ZIP64 EOCD record is not contiguous with its locator")
        # Classic fields that are not saturated must agree with the ZIP64 record.
        if total_entries != 0xFFFF and total_entries != z_total:
            raise ZipFormatError("classic and ZIP64 entry counts disagree")
        if cd_size != 0xFFFFFFFF and cd_size != z_cd_size:
            raise ZipFormatError("classic and ZIP64 central-directory sizes disagree")
        if cd_offset != 0xFFFFFFFF and cd_offset != z_cd_offset:
            raise ZipFormatError("classic and ZIP64 central-directory offsets disagree")
        if z_cd_offset + z_cd_size != z64_eocd_abs:
            raise ZipFormatError("ZIP64 central directory is not contiguous with the ZIP64 EOCD record")
        return CentralDirectoryLocation(z_cd_offset, z_cd_size, z_total, True, eocd_abs)
    if needs_zip64:
        raise ZipFormatError("EOCD is saturated but no ZIP64 locator is present")
    if disk != 0 or cd_disk != 0 or disk_entries != total_entries:
        raise ZipFormatError("multi-disk ZIP archive is unsupported")
    if cd_offset + cd_size != eocd_abs:
        raise ZipFormatError("central directory is not contiguous with the EOCD")
    return CentralDirectoryLocation(cd_offset, cd_size, total_entries, False, eocd_abs)


def _zip64_extra(extra: bytes, usize: int, csize: int, lho: int, disk: int) -> tuple[int, int, int, int]:
    pos = 0
    while pos + 4 <= len(extra):
        header_id, data_len = struct.unpack_from("<HH", extra, pos)
        body = extra[pos + 4 : pos + 4 + data_len]
        if len(body) != data_len:
            raise ZipFormatError("truncated extra field")
        if header_id == 0x0001:
            cursor = 0
            values = []
            for value, width, saturated in (
                (usize, 8, 0xFFFFFFFF),
                (csize, 8, 0xFFFFFFFF),
                (lho, 8, 0xFFFFFFFF),
                (disk, 4, 0xFFFF),
            ):
                if value == saturated:
                    if cursor + width > len(body):
                        raise ZipFormatError("ZIP64 extra field is too short")
                    value = int.from_bytes(body[cursor : cursor + width], "little")
                    cursor += width
                values.append(value)
            return values[0], values[1], values[2], values[3]
        pos += 4 + data_len
    if 0xFFFFFFFF in (usize, csize, lho) or disk == 0xFFFF:
        raise ZipFormatError("saturated central-directory field without ZIP64 extra field")
    return usize, csize, lho, disk


def parse_central_directory(cd: bytes, expected_entries: int) -> list[Member]:
    members: list[Member] = []
    pos = 0
    while pos < len(cd):
        if cd[pos : pos + 4] != CD_SIG or pos + 46 > len(cd):
            raise ZipFormatError(f"bad central-directory header at relative offset {pos}")
        fields = struct.unpack_from("<4s6H3I5H2I", cd, pos)
        flags, method = fields[3], fields[4]
        crc, csize, usize = fields[7], fields[8], fields[9]
        name_len, extra_len, comment_len, disk = fields[10], fields[11], fields[12], fields[13]
        lho = fields[16]
        var_start = pos + 46
        var_end = var_start + name_len + extra_len + comment_len
        if var_end > len(cd):
            raise ZipFormatError("central-directory variable fields overrun the directory")
        name_bytes = cd[var_start : var_start + name_len]
        name = name_bytes.decode("utf-8" if flags & 0x800 else "cp437")
        extra = cd[var_start + name_len : var_start + name_len + extra_len]
        usize, csize, lho, disk = _zip64_extra(extra, usize, csize, lho, disk)
        if disk != 0:
            raise ZipFormatError(f"member {name!r} starts on another disk")
        members.append(Member(name, flags, method, crc, csize, usize, lho, name_len, extra_len))
        pos = var_end
    if len(members) != expected_entries:
        raise ZipFormatError(f"central directory holds {len(members)} entries, EOCD declares {expected_entries}")
    return members


def member_fetch_range(member: Member, cd_offset: int, slack: int = 4096) -> tuple[int, int]:
    """Inclusive byte range covering the local header and compressed data.

    The local header's extra-field length may differ from the central
    directory's, so `slack` extra bytes are requested and the exact boundary
    is resolved from the local header itself.  The range never crosses into
    the central directory.
    """
    start = member.local_header_offset
    end = start + 30 + member.cd_name_len + member.cd_extra_len + member.compressed_size + slack
    end = min(end, cd_offset)
    return start, end - 1


def extract_member(payload: bytes, member: Member) -> bytes:
    """Inflate one member from a payload that starts at its local header."""
    if payload[:4] != LOCAL_SIG or len(payload) < 30:
        raise ZipFormatError(f"{member.name}: missing local file header signature")
    (_, _version, flags, method, _time, _date, crc, csize, usize, name_len, extra_len) = struct.unpack_from(
        "<4s5H3I2H", payload, 0
    )
    name = payload[30 : 30 + name_len].decode("utf-8" if flags & 0x800 else "cp437")
    if name != member.name:
        raise ZipFormatError(f"local header name {name!r} != central directory name {member.name!r}")
    if method != member.method:
        raise ZipFormatError(f"{member.name}: local/central compression methods disagree")
    if flags & 0x1:
        raise ZipFormatError(f"{member.name}: encrypted member")
    if not flags & 0x8:
        # Without a data descriptor the local fields must agree (or be ZIP64-saturated).
        if crc != member.crc32:
            raise ZipFormatError(f"{member.name}: local/central CRC-32 disagree")
        if csize not in (member.compressed_size, 0xFFFFFFFF) or usize not in (member.uncompressed_size, 0xFFFFFFFF):
            raise ZipFormatError(f"{member.name}: local/central sizes disagree")
    data_start = 30 + name_len + extra_len
    data_end = data_start + member.compressed_size
    if data_end > len(payload):
        raise ZipFormatError(f"{member.name}: fetched range ends before the compressed data")
    compressed = payload[data_start:data_end]
    if method == 8:
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            data = inflater.decompress(compressed) + inflater.flush()
        except zlib.error as exc:
            raise ZipFormatError(f"{member.name}: corrupt DEFLATE stream: {exc}") from exc
        if not inflater.eof or inflater.unused_data:
            raise ZipFormatError(f"{member.name}: DEFLATE stream does not end at the declared compressed size")
    elif method == 0:
        data = compressed
    else:
        raise ZipFormatError(f"{member.name}: unsupported compression method {method}")
    if len(data) != member.uncompressed_size:
        raise ZipFormatError(f"{member.name}: inflated {len(data)} bytes, expected {member.uncompressed_size}")
    actual_crc = zlib.crc32(data) & 0xFFFFFFFF
    if actual_crc != member.crc32:
        raise ZipFormatError(f"{member.name}: CRC-32 {actual_crc:08x} != central directory {member.crc32:08x}")
    return data


def parse_wav_float32(wav: bytes, label: str = "wav") -> tuple[bytes, list[str]]:
    """Validate the Arni WAV layout and return (data_chunk_bytes, chunk_ids)."""
    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError(f"{label}: not a RIFF/WAVE file")
    riff_size = struct.unpack_from("<I", wav, 4)[0]
    if riff_size + 8 != len(wav):
        raise ValueError(f"{label}: RIFF size {riff_size}+8 != file size {len(wav)}")
    pos = 12
    fmt = None
    data = None
    fact = None
    peak = None
    chunk_ids: list[str] = []
    while pos < len(wav):
        if pos + 8 > len(wav):
            raise ValueError(f"{label}: truncated chunk header at {pos}")
        chunk_id = wav[pos : pos + 4]
        chunk_size = struct.unpack_from("<I", wav, pos + 4)[0]
        body_start = pos + 8
        body_end = body_start + chunk_size
        if body_end > len(wav):
            raise ValueError(f"{label}: chunk {chunk_id!r} overruns the file")
        chunk_ids.append(chunk_id.decode("latin-1"))
        if chunk_id == b"fmt ":
            if fmt is not None or chunk_size < 16:
                raise ValueError(f"{label}: duplicate or short fmt chunk")
            fmt = struct.unpack_from("<HHIIHH", wav, body_start)
        elif chunk_id == b"data":
            if data is not None:
                raise ValueError(f"{label}: duplicate data chunk")
            data = wav[body_start:body_end]
        elif chunk_id == b"fact":
            if chunk_size < 4:
                raise ValueError(f"{label}: short fact chunk")
            fact = struct.unpack_from("<I", wav, body_start)[0]
        elif chunk_id == b"PEAK":
            # version, timestamp, then one (float value, uint32 position) per channel
            if chunk_size < 16:
                raise ValueError(f"{label}: short PEAK chunk")
            peak = struct.unpack_from("<f I", wav, body_start + 8)
        else:
            raise ValueError(f"{label}: unexpected chunk {chunk_id!r}")
        pos = body_end + (chunk_size & 1)
    expected_fmt = (WAV_FORMAT_IEEE_FLOAT, WAV_CHANNELS, WAV_RATE, WAV_BYTE_RATE, WAV_BLOCK_ALIGN, WAV_BITS)
    if fmt != expected_fmt:
        raise ValueError(f"{label}: fmt {fmt} != expected {expected_fmt}")
    if data is None:
        raise ValueError(f"{label}: missing data chunk")
    if len(data) != WAV_DATA_BYTES:
        raise ValueError(f"{label}: data chunk {len(data)} bytes, expected {WAV_DATA_BYTES}")
    if fact is not None and fact != WAV_VALUES:
        raise ValueError(f"{label}: fact sample length {fact} != {WAV_VALUES}")
    if peak is not None:
        # The writer's PEAK chunk records max |x| and its position: an
        # independent check that the data chunk decodes as float32 samples.
        peak_value, peak_position = peak
        if peak_position >= WAV_VALUES:
            raise ValueError(f"{label}: PEAK position {peak_position} outside the data chunk")
        at_position = abs(struct.unpack_from("<f", data, 4 * peak_position)[0])
        maximum = max(abs(v) for v in struct.unpack(f"<{WAV_VALUES}f", data))
        if not (peak_value == maximum == at_position):
            raise ValueError(
                f"{label}: PEAK chunk ({peak_value} at {peak_position}) disagrees with data max |x| {maximum}"
            )
    return data, chunk_ids


def float32_stats(data: bytes, label: str = "sample") -> dict:
    """Finite/nondegenerate check and stats computed from stored float32 values."""
    if len(data) % 4:
        raise ValueError(f"{label}: byte length is not a multiple of 4")
    values = struct.unpack(f"<{len(data) // 4}f", data)
    minimum = math.inf
    maximum = -math.inf
    zeros = 0
    peak_index = 0
    peak_abs = -1.0
    for index, value in enumerate(values):
        if not math.isfinite(value):
            raise ValueError(f"{label}: non-finite value at index {index}")
        if value < minimum:
            minimum = value
        if value > maximum:
            maximum = value
        if value == 0.0:
            zeros += 1
        magnitude = abs(value)
        if magnitude > peak_abs:
            peak_abs = magnitude
            peak_index = index
    if zeros == len(values):
        raise ValueError(f"{label}: all values are zero")
    if minimum == maximum:
        raise ValueError(f"{label}: constant series")
    on_lattice = sum(1 for value in values if value * INT16_LATTICE_SCALE == round(value * INT16_LATTICE_SCALE))
    lattice_fraction = on_lattice / len(values)
    if not lattice_fraction < MAX_INT16_LATTICE_FRACTION:
        raise ValueError(
            f"{label}: {lattice_fraction:.2%} of values lie on the int16 (2^-15) lattice; widened integer data"
        )
    distinct_bits = len(set(struct.unpack(f"<{len(values)}I", data)))
    if distinct_bits < MIN_DISTINCT_BIT_PATTERNS:
        raise ValueError(f"{label}: only {distinct_bits} distinct float32 bit patterns")
    return {
        "value_count": len(values),
        "min": minimum,
        "max": maximum,
        "zero_count": zeros,
        "peak_abs": peak_abs,
        "peak_index": peak_index,
        "int16_lattice_fraction": lattice_fraction,
        "distinct_bit_patterns": distinct_bits,
    }


def parse_member_name(name: str) -> tuple[int, int, int, int] | None:
    match = NAME_RE.search(name)
    if not match:
        return None
    return tuple(int(x) for x in match.groups())  # type: ignore[return-value]


def select_members(members_by_archive: dict[str, list[Member]]) -> list[tuple[str, Member, tuple[int, int, int, int]]]:
    """Deterministic selection rule.

    For every numClosed k in 0..55 except EXCLUDED_LEVELS (11, 27, 35, whose
    receiver files repeat responses across mic labels), take the lowest numComb outside the
    special block 2..31 for which the sweep_1 impulse response exists for all
    five receivers (mic 1..5) with a central-directory compressed size of at
    least MIN_COMPRESSED_BYTES; emit those five members.  Repeat sweeps 2..5
    are excluded as near-duplicates.  A combination with any missing sweep_1
    (sweeps discarded upstream for non-stationary noise) is skipped in favour
    of the next numComb.

    numComb numbering: 0 = all reflective (numClosed 55), 1 = all absorptive
    (numClosed 0), 2..31 = 30 out-of-sequence special configurations spread
    over many levels, 32..86 = numClosed 54, 87..141 = numClosed 1, then 100
    per level.  The special block is excluded because in several of its
    configurations (numComb 5, 7, 21, 27) multiple receiver labels hold the
    same response (mics 1-3 r >= 0.9997, mics 4-5 r >= 0.9996).
    """
    index: dict[tuple[int, int, int, int], tuple[str, Member]] = {}
    for archive, members in members_by_archive.items():
        for member in members:
            key = parse_member_name(member.name)
            if key is None:
                continue
            if key in index:
                raise ZipFormatError(f"duplicate impulse response {key} in {archive} and {index[key][0]}")
            index[key] = (archive, member)
    selected: list[tuple[str, Member, tuple[int, int, int, int]]] = []
    for k in NUM_CLOSED_RANGE:
        if k in EXCLUDED_LEVELS:
            continue
        combos = sorted({c for (kk, c, _m, _s) in index if kk == k and c not in EXCLUDED_COMBOS})
        chosen = None
        for combo in combos:
            if all(
                (k, combo, mic, SELECTED_SWEEP) in index
                and index[(k, combo, mic, SELECTED_SWEEP)][1].compressed_size >= MIN_COMPRESSED_BYTES
                for mic in MICS
            ):
                chosen = combo
                break
        if chosen is None:
            raise ZipFormatError(f"numClosed={k}: no combination has qualifying sweep_1 members for all five receivers")
        for mic in MICS:
            key = (k, chosen, mic, SELECTED_SWEEP)
            archive, member = index[key]
            selected.append((archive, member, key))
    return selected


def normalized_window(data: bytes, label: str = "sample") -> list[float]:
    """Mean-removed, unit-norm float32 values over DISTINCT_WINDOW."""
    start, end = DISTINCT_WINDOW
    values = struct.unpack_from(f"<{end - start}f", data, 4 * start)
    mean = math.fsum(values) / len(values)
    centered = [v - mean for v in values]
    norm = math.sqrt(math.fsum(v * v for v in centered))
    if norm == 0.0:
        raise ValueError(f"{label}: zero-variance distinctness window")
    return [v / norm for v in centered]


def correlation(a: list[float], b: list[float]) -> float:
    """Zero-lag Pearson r of two normalized_window() vectors."""
    return sum(map(operator.mul, a, b))


def sample_stem(key: tuple[int, int, int, int]) -> str:
    k, combo, mic, sweep = key
    return f"IR_numClosed_{k}_numComb_{combo}_mic_{mic}_sweep_{sweep}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit("arni_zip.py is a helper module")
