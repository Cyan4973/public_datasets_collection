#!/usr/bin/env python3
"""Pure-stdlib NAIF DAF/CK reader for the MRO bus attitude recipe.

Implements just what the recipe needs, following the NAIF DAF and CK
Required Reading documents:

* DAF file record (record 1): identification word, ND/NI, FWARD/BWARD/FREE,
  binary format identifier.
* DAF summary records: NEXT/PREV/NSUM control words followed by NSUM packed
  summaries of ND doubles and NI integers (ND=2, NI=6 for CK).
* CK data type 3 segment layout (with angular velocity, AV flag = 1):

    N pointing records of 7 doubles  [q0, q1, q2, q3, av1, av2, av3]
    N encoded-SCLK time tags
    floor((N-1)/100) time-tag directory entries (every 100th tag)
    NINTS interpolation-interval start times
    floor((NINTS-1)/100) interval-start directory entries
    NINTS, N

The splitter is exact: quaternion and rate words are re-serialised
byte-for-byte (big-endian word -> little-endian word) without any float
arithmetic, so stored values are preserved bit-exactly.
"""
from __future__ import annotations

import array
import math
import struct
import sys

DAF_RECORD_BYTES = 1024
WORD_BYTES = 8
CK_IDWORD = b"DAF/CK  "
CK_ND = 2
CK_NI = 6
SUMMARY_WORDS = CK_ND + (CK_NI + 1) // 2  # 5 doubles = 40 bytes
SUMMARIES_PER_RECORD = (DAF_RECORD_BYTES - 3 * WORD_BYTES) // (SUMMARY_WORDS * WORD_BYTES)  # 25

# Recipe identity checks (screener note 3).
EXPECTED_INSTRUMENT = -74000  # MRO_SPACECRAFT bus
EXPECTED_FRAME = -74900  # MRO_MME_OF_DATE
EXPECTED_TYPE = 3
EXPECTED_AV_FLAG = 1
QUATERNION_NORM_TOLERANCE = 1e-6


class CKError(ValueError):
    pass


def endian_prefix(binary_format: bytes) -> str:
    if binary_format == b"BIG-IEEE":
        return ">"
    if binary_format == b"LTL-IEEE":
        return "<"
    raise CKError(f"unsupported DAF binary format {binary_format!r}")


def parse_file_record(record: bytes) -> dict:
    if len(record) != DAF_RECORD_BYTES:
        raise CKError(f"DAF file record must be {DAF_RECORD_BYTES} bytes, got {len(record)}")
    if record[:8] != CK_IDWORD:
        raise CKError(f"not a DAF/CK file: identification word {record[:8]!r}")
    binary_format = record[88:96]
    endian = endian_prefix(binary_format)
    nd, ni = struct.unpack_from(endian + "ii", record, 8)
    if (nd, ni) != (CK_ND, CK_NI):
        raise CKError(f"unexpected CK summary dimensions ND={nd} NI={ni}")
    internal_name = record[16:76].decode("ascii", errors="replace").rstrip(" \x00")
    fward, bward, free = struct.unpack_from(endian + "iii", record, 76)
    if fward < 2 or bward < fward or free < 1:
        raise CKError(f"implausible DAF pointers FWARD={fward} BWARD={bward} FREE={free}")
    ftpstr = record[699:727]
    if not ftpstr.startswith(b"FTPSTR:") or not ftpstr.endswith(b":ENDFTP"):
        raise CKError("DAF FTP validation string is missing or corrupted")
    return {
        "endian": endian,
        "binary_format": binary_format.decode("ascii"),
        "nd": nd,
        "ni": ni,
        "internal_name": internal_name,
        "fward": fward,
        "bward": bward,
        "free": free,
    }


def parse_summary_record(record: bytes, endian: str, record_number: int) -> dict:
    """Parse one DAF summary record. Returns control words and summaries."""
    if len(record) != DAF_RECORD_BYTES:
        raise CKError(f"summary record {record_number} must be {DAF_RECORD_BYTES} bytes")
    nxt, prv, nsum = struct.unpack_from(endian + "ddd", record, 0)
    for label, value in (("NEXT", nxt), ("PREV", prv), ("NSUM", nsum)):
        if not math.isfinite(value) or value != int(value) or value < 0:
            raise CKError(f"summary record {record_number}: non-integral {label}={value!r}")
    nsum_i = int(nsum)
    if nsum_i > SUMMARIES_PER_RECORD:
        raise CKError(f"summary record {record_number}: NSUM={nsum_i} exceeds capacity {SUMMARIES_PER_RECORD}")
    summaries = []
    for index in range(nsum_i):
        offset = 3 * WORD_BYTES + index * SUMMARY_WORDS * WORD_BYTES
        begin, end = struct.unpack_from(endian + "dd", record, offset)
        inst, frame, data_type, av_flag, start, stop = struct.unpack_from(endian + "6i", record, offset + 16)
        summaries.append(
            {
                "index_in_record": index,
                "sclk_begin": begin,
                "sclk_end": end,
                "instrument": inst,
                "frame": frame,
                "data_type": data_type,
                "av_flag": av_flag,
                "start_word": start,
                "end_word": stop,
            }
        )
    return {"record_number": record_number, "next": int(nxt), "prev": int(prv), "nsum": nsum_i, "summaries": summaries}


def check_summary_identity(summary: dict, label: str) -> None:
    got = (summary["instrument"], summary["frame"], summary["data_type"], summary["av_flag"])
    want = (EXPECTED_INSTRUMENT, EXPECTED_FRAME, EXPECTED_TYPE, EXPECTED_AV_FLAG)
    if got != want:
        raise CKError(f"{label}: summary (inst, frame, type, av)={got}, expected {want}")
    if summary["start_word"] < 1 or summary["end_word"] < summary["start_word"]:
        raise CKError(f"{label}: invalid word addresses {summary['start_word']}..{summary['end_word']}")
    if not (math.isfinite(summary["sclk_begin"]) and math.isfinite(summary["sclk_end"])):
        raise CKError(f"{label}: non-finite SCLK coverage")
    if summary["sclk_begin"] > summary["sclk_end"]:
        raise CKError(f"{label}: SCLK coverage begins after it ends")


def type3_expected_length(n: int, nints: int) -> int:
    return 7 * n + n + (n - 1) // 100 + nints + (nints - 1) // 100 + 2


def decode_words(raw: bytes, endian: str) -> array.array:
    if len(raw) % WORD_BYTES:
        raise CKError(f"segment byte length {len(raw)} is not a multiple of 8")
    words = array.array("d")
    if words.itemsize != WORD_BYTES:
        raise CKError("platform double is not 8 bytes")
    words.frombytes(raw)
    native = "<" if sys.byteorder == "little" else ">"
    if endian != native:
        words.byteswap()
    return words


def _exact_count(value: float, label: str) -> int:
    if not math.isfinite(value) or value != int(value) or value < 1:
        raise CKError(f"invalid type-3 {label} word {value!r}")
    return int(value)


def split_type3(raw: bytes, endian: str, summary: dict | None = None, label: str = "segment") -> dict:
    """Split one CK type-3 (AV flag 1) segment and validate its structure.

    Returns little-endian byte strings for the quaternion (N x 4) and rate
    (N x 3) blocks and the epoch block (N), plus structural metadata.
    """
    words = decode_words(raw, endian)
    length = len(words)
    if length < 10:
        raise CKError(f"{label}: segment too short ({length} words)")
    nints = _exact_count(words[-2], "NINTS")
    n = _exact_count(words[-1], "N")
    expected = type3_expected_length(n, nints)
    if expected != length:
        raise CKError(f"{label}: length {length} != 7N+N+floor((N-1)/100)+NINTS+floor((NINTS-1)/100)+2 = {expected} (N={n}, NINTS={nints})")
    if nints > n:
        raise CKError(f"{label}: NINTS={nints} exceeds N={n}")

    epoch_offset = 7 * n
    epochs = words[epoch_offset : epoch_offset + n]
    dir_offset = epoch_offset + n
    n_dir = (n - 1) // 100
    epoch_dir = words[dir_offset : dir_offset + n_dir]
    ints_offset = dir_offset + n_dir
    starts = words[ints_offset : ints_offset + nints]
    n_int_dir = (nints - 1) // 100
    int_dir = words[ints_offset + nints : ints_offset + nints + n_int_dir]

    for index, value in enumerate(words[: 7 * n]):
        if not math.isfinite(value):
            raise CKError(f"{label}: non-finite pointing word at record {index // 7}")
    previous = -math.inf
    for index, tick in enumerate(epochs):
        if not math.isfinite(tick) or tick <= previous:
            raise CKError(f"{label}: epochs not strictly increasing at record {index}")
        previous = tick
    for j, value in enumerate(epoch_dir):
        if value != epochs[100 * (j + 1) - 1]:
            raise CKError(f"{label}: epoch directory entry {j} does not match epoch {100 * (j + 1) - 1}")
    if starts[0] != epochs[0]:
        raise CKError(f"{label}: first interval start differs from first epoch")
    epoch_set = set(epochs)
    previous = -math.inf
    for k, value in enumerate(starts):
        if value <= previous or value not in epoch_set:
            raise CKError(f"{label}: interval start {k} is not an increasing epoch")
        previous = value
    for j, value in enumerate(int_dir):
        if value != starts[100 * (j + 1) - 1]:
            raise CKError(f"{label}: interval directory entry {j} mismatch")

    worst_norm = 0.0
    for record in range(n):
        base = 7 * record
        q0, q1, q2, q3 = words[base : base + 4]
        deviation = abs(math.sqrt(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3) - 1.0)
        if deviation > worst_norm:
            worst_norm = deviation
    if worst_norm > QUATERNION_NORM_TOLERANCE:
        raise CKError(f"{label}: quaternion norm deviates from 1 by {worst_norm:.3e}")

    if summary is not None:
        if epochs[0] < summary["sclk_begin"] or epochs[-1] > summary["sclk_end"]:
            raise CKError(f"{label}: epochs fall outside the summary SCLK coverage")

    # Byte-exact re-serialisation: take the original big/little-endian words
    # and emit little-endian words without float conversion.
    le_words = array.array("d", words[: 8 * n])  # pointing records + epochs
    if sys.byteorder != "little":
        le_words.byteswap()
    pointing = le_words[: 7 * n].tobytes()
    quaternion = bytearray(n * 4 * WORD_BYTES)
    rate = bytearray(n * 3 * WORD_BYTES)
    record_bytes = 7 * WORD_BYTES
    for record in range(n):
        src = record * record_bytes
        quaternion[record * 32 : record * 32 + 32] = pointing[src : src + 32]
        rate[record * 24 : record * 24 + 24] = pointing[src + 32 : src + 56]
    epoch_bytes = le_words[7 * n : 8 * n].tobytes()
    return {
        "n": n,
        "nints": nints,
        "length_words": length,
        "quaternion_le": bytes(quaternion),
        "rate_le": bytes(rate),
        "epoch_le": epoch_bytes,
        "first_epoch": epochs[0],
        "last_epoch": epochs[-1],
        "max_quaternion_norm_deviation": worst_norm,
    }


def le_doubles(raw: bytes) -> array.array:
    values = array.array("d")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values
