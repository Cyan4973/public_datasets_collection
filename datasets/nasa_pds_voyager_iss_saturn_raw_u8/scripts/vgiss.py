#!/usr/bin/env python3
"""Shared helpers for the Voyager ISS Saturn raw-frame recipe (download checks, discover, build).

verify.py deliberately does NOT import this module; it re-implements the
index parsing, selection rule, label checks and frame decode on its own.

File layout of a VGISS RAW image (Cnnnnnnn_RAW.IMG, 823,296 bytes), taken
from the VICAR label of the file itself (LBLSIZE=1024 RECSIZE=1024 NLB=2
NBB=224 NL=800 NS=800 EOL=1):

  bytes      0 -   1023  VICAR label (ASCII)
  bytes   1024 -   3071  two VICAR binary-label records (NLB=2): engineering
                         header and a 256-bin x uint32 DN histogram
  bytes   3072 - 822271  800 image records of 1024 bytes:
                         224-byte binary line prefix (NBB) + 800 uint8 DN
  bytes 822272 - 823295  VICAR extension label (EOL=1)

The detached PDS label says ^IMAGE = record 2, which ignores the two VICAR
binary-label records; following it would read the binary headers as image
lines 1-2 and drop the last two real image lines. The VICAR offset is
confirmed by the embedded histogram (it equals the histogram of records
4-803 exactly for frames without data dropouts) and by the FDS clock count
stored in each line prefix.
"""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

DATASET_ID = "nasa_pds_voyager_iss_saturn_raw_u8"
SERIES_ID = "vg2_issn_saturn_raw_dn_u8"
VOLUME = "VGISS_0005"
BUCKET = "https://asc-pds-voyager.s3.us-west-2.amazonaws.com"

FILE_BYTES = 823_296
RECORD = 1024
LBLSIZE = 1024
NLB = 2
NBB = 224
LINES = 800
SAMPLES = 800
FRAME = LINES * SAMPLES
IMAGE_OFFSET = LBLSIZE + NLB * RECORD          # 3072
EOL_OFFSET = IMAGE_OFFSET + LINES * RECORD     # 822272
MAX_FILL_LINES = 40                            # frames with more all-zero lines are excluded
MIN_DISTINCT = 16

# INDEX.TAB fixed-width columns (1-based START_BYTE, BYTES) from INDEX.LBL.
INDEX_ROW_BYTES = 395
INDEX_COLUMNS = {
    "volume_name": (2, 10),
    "file_specification_name": (15, 39),
    "product_id": (57, 30),
    "product_type": (90, 29),
    "spacecraft_name": (122, 9),
    "mission_phase_name": (134, 17),
    "target_name": (154, 10),
    "image_id": (167, 10),
    "image_number": (179, 8),
    "image_time": (189, 19),
    "earth_received_time": (211, 19),
    "instrument_name": (233, 19),
    "scan_mode": (255, 4),
    "shutter_mode": (262, 6),
    "gain_mode": (271, 4),
    "edit_mode": (278, 4),
    "filter_name": (285, 6),
    "filter_number": (293, 1),
    "exposure_duration": (295, 7),
    "note": (304, 80),
    "data_anomaly": (387, 6),
}
SELECTED_TARGETS = ("SATURN", "S RINGS")

# Required detached-label values (top level and IMAGE object).
LABEL_REQUIRED = {
    "PDS_VERSION_ID": "PDS3",
    "RECORD_TYPE": "FIXED_LENGTH",
    "RECORD_BYTES": "1024",
    "FILE_RECORDS": "804",
    "DATA_SET_ID": "VG1/VG2-S-ISS-2/3/4/6-PROCESSED-V1.0",
    "PRODUCT_TYPE": "DECOMPRESSED_RAW_IMAGE",
    "SPACECRAFT_NAME": "VOYAGER 2",
    "SPACECRAFT_ID": "VG2",
    "INSTRUMENT_ID": "ISSN",
    "MISSION_PHASE_NAME": "SATURN ENCOUNTER",
    "SCAN_MODE_ID": "3:1",
    "GAIN_MODE_ID": "LOW",
    "EDIT_MODE_ID": "1:1",
}
IMAGE_REQUIRED = {
    "LINES": "800",
    "LINE_SAMPLES": "800",
    "LINE_PREFIX_BYTES": "224",
    "SAMPLE_TYPE": "UNSIGNED_INTEGER",
    "SAMPLE_BITS": "8",
}
VICAR_REQUIRED = {
    "LBLSIZE": "1024", "FORMAT": "BYTE", "TYPE": "IMAGE", "DIM": "3", "EOL": "1", "RECSIZE": "1024",
    "ORG": "BSQ", "NL": "800", "NS": "800", "NB": "1", "N1": "800", "N2": "800", "N3": "1",
    "NBB": "224", "NLB": "2", "INTFMT": "LOW",
}


class FrameError(Exception):
    pass


# ---------------------------------------------------------------- index / selection

def parse_index(path: Path) -> list[dict]:
    blob = path.read_bytes()
    if len(blob) % INDEX_ROW_BYTES:
        raise FrameError(f"{path.name}: size {len(blob)} is not a multiple of {INDEX_ROW_BYTES}")
    rows = []
    for start in range(0, len(blob), INDEX_ROW_BYTES):
        rec = blob[start:start + INDEX_ROW_BYTES]
        if rec[-2:] != b"\r\n":
            raise FrameError(f"{path.name}: row at byte {start} lacks CRLF")
        text = rec.decode("ascii")
        row = {}
        for name, (first, width) in INDEX_COLUMNS.items():
            row[name] = text[first - 1:first - 1 + width].strip()
        rows.append(row)
    return rows


def is_selected(row: dict) -> bool:
    return (
        row["volume_name"] == VOLUME
        and row["product_type"] == "DECOMPRESSED_RAW_IMAGE"
        and row["spacecraft_name"] == "VOYAGER 2"
        and row["mission_phase_name"] == "SATURN ENCOUNTER"
        and row["instrument_name"] == "NARROW ANGLE CAMERA"
        and row["scan_mode"] == "3:1"
        and row["edit_mode"] == "1:1"
        and row["gain_mode"] == "LOW"
        and row["target_name"] in SELECTED_TARGETS
        and row["shutter_mode"] != "BODARK"
        and not row["file_specification_name"].startswith("CALIB/")
        and row["data_anomaly"] == "NONE"
        and row["exposure_duration"] != "-99.999"
    )


def select(rows: list[dict]) -> list[dict]:
    chosen = [row for row in rows if is_selected(row)]
    chosen.sort(key=lambda row: (float(row["image_number"]), row["product_id"]))
    return chosen


def product_name(image_number: str) -> str:
    major, minor = image_number.split(".")
    return f"C{int(major):05d}{int(minor):02d}"


def read_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


# ---------------------------------------------------------------- labels

def parse_pds_label(text: str) -> tuple[dict, dict]:
    """Return (top-level keywords, IMAGE-object keywords); values unquoted, units dropped."""
    top: dict[str, str] = {}
    image: dict[str, str] = {}
    stack: list[str] = []
    lines = text.replace("\r", "").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.strip() == "END":
            break
        match = re.match(r"^\s*([A-Z0-9_^]+)\s*=\s*(.*)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value == "" or (value.startswith('"') and value.count('"') == 1):
            # continued value (quoted multi-line or value on next line)
            while i < len(lines):
                value += " " + lines[i].strip()
                i += 1
                if value.count('"') != 1 and value.strip():
                    break
        value = re.sub(r"/\*.*?\*/", "", value).strip()
        if key == "OBJECT":
            stack.append(value)
            continue
        if key == "END_OBJECT":
            if stack:
                stack.pop()
            continue
        value = re.sub(r"\s*<[^>]*>\s*$", "", value).strip()
        if value.startswith('"') and value.endswith('"'):
            value = " ".join(value[1:-1].split())
        if not stack:
            top.setdefault(key, value)
        elif stack == ["IMAGE"]:
            image.setdefault(key, value)
    return top, image


def parse_vicar_label(blob: bytes) -> dict[str, str]:
    text = blob.rstrip(b"\x00").decode("ascii")
    values: dict[str, str] = {}
    for match in re.finditer(r"([A-Z0-9_]+)=('(?:[^']|'')*'|[^ ]+)", text):
        key, value = match.group(1), match.group(2)
        if value.startswith("'"):
            value = value[1:-1].replace("''", "'")
        values.setdefault(key, value)
    return values


def check_label(text: str, image_number: str, product: str) -> dict:
    top, image = parse_pds_label(text)
    for key, value in LABEL_REQUIRED.items():
        if top.get(key) != value:
            raise FrameError(f"{product}: label {key}={top.get(key)!r}, expected {value!r}")
    for key, value in IMAGE_REQUIRED.items():
        if image.get(key) != value:
            raise FrameError(f"{product}: label IMAGE.{key}={image.get(key)!r}, expected {value!r}")
    if top.get("TARGET_NAME") not in SELECTED_TARGETS:
        raise FrameError(f"{product}: label TARGET_NAME={top.get('TARGET_NAME')!r}")
    if top.get("SHUTTER_MODE_ID") in (None, "BODARK"):
        raise FrameError(f"{product}: label SHUTTER_MODE_ID={top.get('SHUTTER_MODE_ID')!r}")
    if top.get("IMAGE_NUMBER") != image_number:
        raise FrameError(f"{product}: label IMAGE_NUMBER={top.get('IMAGE_NUMBER')!r}, expected {image_number}")
    if top.get("PRODUCT_ID") != f"{product}_RAW.IMG.V1":
        raise FrameError(f"{product}: label PRODUCT_ID={top.get('PRODUCT_ID')!r}")
    if top.get("^IMAGE") != f'("{product}_RAW.IMG", 2)':
        raise FrameError(f"{product}: unexpected ^IMAGE pointer {top.get('^IMAGE')!r}")
    return top


# ---------------------------------------------------------------- frame decode

def check_vicar(raw: bytes, image_number: str, product: str) -> dict[str, str]:
    if len(raw) != FILE_BYTES:
        raise FrameError(f"{product}: {len(raw)} bytes, expected {FILE_BYTES}")
    vicar = parse_vicar_label(raw[:LBLSIZE])
    for key, value in VICAR_REQUIRED.items():
        if vicar.get(key) != value:
            raise FrameError(f"{product}: VICAR {key}={vicar.get(key)!r}, expected {value!r}")
    lab02, lab03, lab04 = vicar.get("LAB02", ""), vicar.get("LAB03", ""), vicar.get("LAB04", "")
    if not lab02.startswith("VGR-2") or f"FDS {image_number}" not in lab02:
        raise FrameError(f"{product}: VICAR LAB02 {lab02!r} does not name VGR-2 FDS {image_number}")
    if not lab03.startswith("NA CAMERA") or "SCAN RATE  3:1" not in lab03:
        raise FrameError(f"{product}: VICAR LAB03 {lab03!r} is not NA camera at scan rate 3:1")
    if "FULL" not in lab04:
        raise FrameError(f"{product}: VICAR LAB04 {lab04!r} lacks FULL resolution")
    if not raw[EOL_OFFSET:EOL_OFFSET + 8] == b"LBLSIZE=":
        raise FrameError(f"{product}: no VICAR extension label at byte {EOL_OFFSET}")
    return vicar


def decode(raw: bytes, image_number: str, product: str) -> tuple[bytes, dict]:
    """Return the 800x800 DN array (row-major, first image line first) and structure stats."""
    check_vicar(raw, image_number, product)
    major, minor = (int(part) for part in image_number.split("."))
    pixels = bytearray()
    fill_lines = 0
    fds_ok = 0
    fds_present = 0
    for line in range(LINES):
        start = IMAGE_OFFSET + line * RECORD
        prefix = raw[start:start + NBB]
        row = raw[start + NBB:start + RECORD]
        pixels += row
        if not any(row):
            fill_lines += 1
        if any(prefix[22:25]):          # lines whose prefix FDS field was not zeroed
            fds_present += 1
            fds_major = prefix[22] | (prefix[23] << 8)
            if major <= fds_major <= major + 8:
                fds_ok += 1
    line0 = raw[IMAGE_OFFSET:IMAGE_OFFSET + NBB]
    line0_fds = (line0[22] | (line0[23] << 8), line0[24])
    if line0_fds != (major, minor):
        raise FrameError(f"{product}: first image-line prefix FDS {line0_fds} != image number {image_number}")
    if fds_ok < fds_present * 0.9:
        raise FrameError(f"{product}: only {fds_ok}/{fds_present} line-prefix FDS counts are within 8 of the frame FDS count")
    pixels = bytes(pixels)
    histogram = [pixels.count(value) for value in range(256)]
    embedded = [int.from_bytes(raw[LBLSIZE + RECORD + 4 * i:LBLSIZE + RECORD + 4 * i + 4], "little") for i in range(256)]
    stats = {
        "fill_lines": fill_lines,
        "zero_pixels": histogram[0],
        "saturated_pixels": histogram[255],
        "minimum": next(i for i in range(256) if histogram[i]),
        "maximum": next(i for i in range(255, -1, -1) if histogram[i]),
        "distinct_values": sum(1 for count in histogram if count),
        "mean": round(sum(i * c for i, c in enumerate(histogram)) / FRAME, 4),
        "embedded_histogram_exact": embedded == histogram,
        "histogram": histogram,
    }
    return pixels, stats


def excluded_reason(stats: dict) -> str:
    """Deterministic exclusion rule shared with verify.py ('' = keep)."""
    if stats["fill_lines"] > MAX_FILL_LINES:
        return f"fill_lines={stats['fill_lines']}>{MAX_FILL_LINES}"
    if stats["distinct_values"] < MIN_DISTINCT:
        return f"distinct_values={stats['distinct_values']}<{MIN_DISTINCT}"
    return ""


def digests(blob: bytes) -> tuple[str, str]:
    return hashlib.md5(blob).hexdigest(), hashlib.sha256(blob).hexdigest()
