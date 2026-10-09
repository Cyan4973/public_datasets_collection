"""Shared constants and parsers for nasa_pds_cassini_rpws_wbr_10khz_waveform_u8.

Pure standard library. Used by discover.py, check_payload.py and build.py.
verify.py deliberately re-implements the record walk instead of importing this.

Cassini RPWS WBR full-resolution product (T<yyyyddd>_<hh>_<band>KHZ<n>_WBRFR.DAT):
fixed-length records, each a 32-byte big-endian row prefix
(RPWS_WBR_WFR_ROW_PREFIX.FMT) followed by RECORD_BYTES-32 sample bytes of
which the first SAMPLES are valid unsigned 8-bit waveform DN.

Prefix byte offsets (0-based; the FMT START_BYTE values are 1-based):
  12-13 RECORD_BYTES (MSB u16)   14-15 SAMPLES (MSB u16)
  18 VALIDITY_FLAG bits (0x40 = WBR data)
  19 STATUS_FLAG bits (0x80 AGC_ENABLE, 0x20 TIMEOUT, 0x10 SUSPECT)
  20 FREQUENCY_BAND (2 = 10 kHz filter, 36 us)   21 GAIN   22 ANTENNA (0 = Ex)
  23 AGC
"""
from __future__ import annotations

import re
import struct

DATASET_ID = "nasa_pds_cassini_rpws_wbr_10khz_waveform_u8"
SERIES_ID = "rpws_wbr_10khz_ex_waveform_u8"
BASE_URL = "https://space.physics.uiowa.edu/pds"
DATA_SET_ID = "CO-V/E/J/S/SS-RPWS-2-REFDR-WBRFULL-V1.0"

# Product name pattern: only the 10-kHz baseband products. 75KHZ (75-kHz
# baseband), 5KHZ, 325KHZ, 2025KHZ, 10025KHZ ... (frequency-translated HF)
# products never match because the band token must be exactly "10KHZ".
PRODUCT_RE = re.compile(r"^T(\d{7})_(\d{2})_10KHZ(\d)_WBRFR$")

PREFIX_BYTES = 32
BAND_10KHZ = 2
ANTENNA_EX = 0
VALIDITY_WBR = 0x40
STATUS_TIMEOUT = 0x20
STATUS_SUSPECT = 0x10
ALLOWED_RECORD_BYTES = {1056, 2080, 4128, 6176, 8224}

LABEL_REQUIRED = [
    ("DATA_SET_ID", '"' + DATA_SET_ID + '"'),
    ("INSTRUMENT_ID", "RPWS"),
    ("SECTION_ID", "WBR"),
    ("STANDARD_DATA_PRODUCT_ID", "RPWS_WIDEBAND_FULL"),
    ("SAMPLING_PARAMETER_INTERVAL", "0.000036"),
    ("DATA_TYPE", "UNSIGNED_INTEGER"),
    ("ITEM_BYTES", "1"),
    ("OFFSET", "-127.5"),
    ("VALID_MINIMUM", "0"),
    ("VALID_MAXIMUM", "255"),
    ("ROW_PREFIX_BYTES", "32"),
]


def label_values(text: str) -> dict[str, list[str]]:
    """Collect KEY = value pairs (first line only of each value)."""
    values: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z_^]+)\s*=\s*(.*?)\s*$", line)
        if m:
            values.setdefault(m.group(1), []).append(m.group(2))
    return values


def check_label(text: str, product: str, dat_size: int) -> dict:
    """Validate a detached PDS3 label; return record_bytes/file_records."""
    vals = label_values(text)
    problems = []
    for key, want in LABEL_REQUIRED:
        got = vals.get(key, [])
        if not got or any(g != want for g in got):
            problems.append(f"{key}={got!r} want {want!r}")
    if vals.get("PRODUCT_ID") != [f'"{product}_V1"']:
        problems.append(f"PRODUCT_ID={vals.get('PRODUCT_ID')!r}")
    if vals.get("RECORD_TYPE") != ["FIXED_LENGTH"]:
        problems.append(f"RECORD_TYPE={vals.get('RECORD_TYPE')!r}")
    try:
        record_bytes = int(vals["RECORD_BYTES"][0])
        file_records = int(vals["FILE_RECORDS"][0])
    except (KeyError, ValueError, IndexError):
        raise ValueError(f"{product}: label lacks RECORD_BYTES/FILE_RECORDS")
    if record_bytes not in ALLOWED_RECORD_BYTES:
        problems.append(f"RECORD_BYTES={record_bytes}")
    if f'"{product}.DAT"' not in text:
        problems.append("label does not point at its DAT file")
    if record_bytes * file_records != dat_size:
        problems.append(f"RECORD_BYTES*FILE_RECORDS={record_bytes * file_records} != DAT size {dat_size}")
    if problems:
        raise ValueError(f"{product}: label check failed: " + "; ".join(problems))
    return {"record_bytes": record_bytes, "file_records": file_records}


def iter_records(data: bytes, record_bytes: int, allow_partial_tail: bool = False):
    """Yield parsed row prefixes and record offsets; strict structural checks."""
    n = len(data)
    if not allow_partial_tail and n % record_bytes:
        raise ValueError(f"data length {n} not a multiple of RECORD_BYTES {record_bytes}")
    off = 0
    while off + record_bytes <= n:
        rb, ns = struct.unpack_from(">HH", data, off + 12)
        if rb != record_bytes:
            raise ValueError(f"record at {off}: RECORD_BYTES {rb} != label {record_bytes}")
        if ns > record_bytes - PREFIX_BYTES:
            raise ValueError(f"record at {off}: SAMPLES {ns} exceeds capacity {record_bytes - PREFIX_BYTES}")
        yield {
            "offset": off,
            "samples": ns,
            "validity": data[off + 18],
            "status": data[off + 19],
            "band": data[off + 20],
            "gain": data[off + 21],
            "antenna": data[off + 22],
            "agc": data[off + 23],
        }
        off += record_bytes


def keep_record(rec: dict) -> bool:
    """Selection rule shared by build (verify re-implements it)."""
    return (
        rec["band"] == BAND_10KHZ
        and rec["antenna"] == ANTENNA_EX
        and rec["validity"] & VALIDITY_WBR
        and not rec["status"] & (STATUS_TIMEOUT | STATUS_SUSPECT)
        and rec["samples"] > 0
    )


def extract(data: bytes, record_bytes: int):
    """Return (payload bytes, stats) for one complete product file."""
    out = bytearray()
    stats = {"records": 0, "kept_records": 0, "dropped_antenna": 0, "dropped_band": 0,
             "dropped_flag": 0, "dropped_empty": 0, "antennas": {}, "bands": {},
             "sample_lengths": {}, "gains": {}}
    for rec in iter_records(data, record_bytes):
        stats["records"] += 1
        stats["antennas"][str(rec["antenna"])] = stats["antennas"].get(str(rec["antenna"]), 0) + 1
        stats["bands"][str(rec["band"])] = stats["bands"].get(str(rec["band"]), 0) + 1
        if rec["band"] != BAND_10KHZ:
            stats["dropped_band"] += 1
            continue
        if rec["antenna"] != ANTENNA_EX:
            stats["dropped_antenna"] += 1
            continue
        if not rec["validity"] & VALIDITY_WBR or rec["status"] & (STATUS_TIMEOUT | STATUS_SUSPECT):
            stats["dropped_flag"] += 1
            continue
        if rec["samples"] == 0:
            stats["dropped_empty"] += 1
            continue
        assert keep_record(rec)
        start = rec["offset"] + PREFIX_BYTES
        out += data[start:start + rec["samples"]]
        stats["kept_records"] += 1
        key = str(rec["samples"])
        stats["sample_lengths"][key] = stats["sample_lengths"].get(key, 0) + 1
        g = str(rec["gain"] & 0x07)
        stats["gains"][g] = stats["gains"].get(g, 0) + 1
    return bytes(out), stats
