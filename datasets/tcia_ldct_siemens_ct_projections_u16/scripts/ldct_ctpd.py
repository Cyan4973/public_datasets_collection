#!/usr/bin/env python3
"""TCIA LDCT-and-Projection-data Siemens full-dose DICOM-CT-PD projection views.

Pure standard-library helper used by download.sh, build.sh and verify.sh.

Subcommands
  selftest        parse synthetic DICOM-CT-PD objects (valid and corrupted)
  check-series    validate the live NBIA getSeries listing against series_pins.tsv
  check-sops      validate one getSOPInstanceUIDs JSON listing
  select          derive the deterministic per-series view selection
  check-instance  validate one fetched DICOM-CT-PD instance
  inventory       re-validate every selected instance and write sizes/hashes
  build           emit one raw little-endian uint16 sample per projection view
  verify          independently re-derive and check every output
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import sys
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "tcia_ldct_siemens_ct_projections_u16"
SERIES_ID = "siemens_full_dose_projection_view_u16"
COLLECTION = "LDCT-and-Projection-data"
LICENSE_URI = "https://creativecommons.org/licenses/by/4.0/"
LICENSE_NAME = "Creative Commons Attribution 4.0 International License"
RAW_DATA_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.66"
IMPLICIT_VR_LE = "1.2.840.10008.1.2"
MAYO_CREATOR = "CtProjectionData-MayoClinc-v1"
PRIVATE_GROUPS = (0x7029, 0x7031, 0x7033, 0x7037, 0x7039, 0x7041)
ROWS = 736  # DICOM Rows == DICOM-CT-PD NumberofDetectorColumns (channels)
COLUMNS = 64  # DICOM Columns == DICOM-CT-PD NumberofDetectorRows
VALUE_COUNT = ROWS * COLUMNS
PIXEL_BYTES = VALUE_COUNT * 2
MIN_FILE_BYTES = 98_000
MAX_FILE_BYTES = 101_000
PER_SERIES = 20
EXPECTED_SERIES = 100
MIN_DISTINCT_VALUES = 256
BODY_PART = {"C": "CHEST", "L": "ABDOMEN"}
UID_RE = re.compile(r"[0-9]+(\.[0-9]+)+")
PIXEL_TAG = (0x7FE0, 0x0010)
PIXEL_HEADER = struct.pack("<HHI", 0x7FE0, 0x0010, PIXEL_BYTES)

T_SOP_CLASS = (0x0008, 0x0016)
T_SOP_INSTANCE = (0x0008, 0x0018)
T_MODALITY = (0x0008, 0x0060)
T_MANUFACTURER = (0x0008, 0x0070)
T_SERIES_DESCRIPTION = (0x0008, 0x103E)
T_PATIENT_ID = (0x0010, 0x0020)
T_BODY_PART = (0x0018, 0x0015)
T_KVP = (0x0018, 0x0060)
T_TUBE_CURRENT = (0x0018, 0x1151)
T_STUDY_UID = (0x0020, 0x000D)
T_SERIES_UID = (0x0020, 0x000E)
T_INSTANCE_NUMBER = (0x0020, 0x0013)
T_SAMPLES_PER_PIXEL = (0x0028, 0x0002)
T_PHOTOMETRIC = (0x0028, 0x0004)
T_ROWS = (0x0028, 0x0010)
T_COLUMNS = (0x0028, 0x0011)
T_BITS_ALLOCATED = (0x0028, 0x0100)
T_BITS_STORED = (0x0028, 0x0101)
T_HIGH_BIT = (0x0028, 0x0102)
T_PIXEL_REPRESENTATION = (0x0028, 0x0103)
T_SMALLEST = (0x0028, 0x0106)
T_LARGEST = (0x0028, 0x0107)
T_RESCALE_INTERCEPT = (0x0028, 0x1052)
T_RESCALE_SLOPE = (0x0028, 0x1053)
T_DET_ROWS = (0x7029, 0x1010)
T_DET_COLUMNS = (0x7029, 0x1011)
T_DET_SHAPE = (0x7029, 0x100B)
T_ANGULAR_POSITION = (0x7031, 0x1001)
T_AXIAL_POSITION = (0x7031, 0x1002)
T_FFS_MODE = (0x7033, 0x100E)
T_ANGULAR_STEPS = (0x7033, 0x1013)
T_PROJECTION_TYPE = (0x7037, 0x1009)
T_PROJECTION_GEOMETRY = (0x7037, 0x100A)
T_PREPROCESSING_FLAGS = tuple((0x7039, element) for element in range(0x1003, 0x100A))
T_LOG_FLAG = (0x7039, 0x1009)
T_WATER_MU = (0x7041, 0x1001)


class DicomError(ValueError):
    pass


# --------------------------------------------------------------------------
# DICOM walker
# --------------------------------------------------------------------------

def parse_meta(data: bytes) -> tuple[dict[tuple[int, int], bytes], int]:
    """Parse the Explicit VR Little Endian group-0002 file meta header."""
    if len(data) < 144 or data[128:132] != b"DICM":
        raise DicomError("missing DICM preamble")
    pos = 132
    meta: dict[tuple[int, int], bytes] = {}
    group, element = struct.unpack_from("<HH", data, pos)
    if (group, element) != (0x0002, 0x0000) or data[pos + 4 : pos + 6] != b"UL":
        raise DicomError("file meta header does not start with (0002,0000) UL")
    (meta_length,) = struct.unpack_from("<I", data, pos + 8)
    end = pos + 12 + meta_length
    if end > len(data):
        raise DicomError("truncated file meta header")
    pos += 12
    while pos < end:
        if pos + 8 > end:
            raise DicomError("truncated meta element header")
        group, element = struct.unpack_from("<HH", data, pos)
        if group != 0x0002:
            raise DicomError("non-0002 element inside the meta group length")
        vr = data[pos + 4 : pos + 6]
        if vr in (b"OB", b"OW", b"OF", b"SQ", b"UT", b"UN"):
            (length,) = struct.unpack_from("<I", data, pos + 8)
            value_offset = pos + 12
        else:
            (length,) = struct.unpack_from("<H", data, pos + 6)
            value_offset = pos + 8
        if length == 0xFFFFFFFF or value_offset + length > end:
            raise DicomError("bad meta element length")
        meta[(group, element)] = data[value_offset : value_offset + length]
        pos = value_offset + length
    if pos != end:
        raise DicomError("meta group length mismatch")
    return meta, end


def _header(data: bytes, pos: int, end: int) -> tuple[int, int, int]:
    if pos + 8 > end:
        raise DicomError(f"truncated element header at offset {pos}")
    return struct.unpack_from("<HHI", data, pos)


def _skip_undefined_sequence(data: bytes, pos: int, end: int, depth: int) -> int:
    """Skip the items of an undefined-length Implicit VR sequence; return the
    offset just after its (FFFE,E0DD) delimiter."""
    if depth > 16:
        raise DicomError("sequence nesting too deep")
    while True:
        group, element, length = _header(data, pos, end)
        if (group, element) == (0xFFFE, 0xE0DD):
            if length != 0:
                raise DicomError("sequence delimiter with nonzero length")
            return pos + 8
        if (group, element) != (0xFFFE, 0xE000):
            raise DicomError(f"expected item tag at offset {pos}, got ({group:04X},{element:04X})")
        if length == 0xFFFFFFFF:
            pos = _walk(data, pos + 8, end, depth + 1, None, until_item_delimiter=True)
        else:
            item_end = pos + 8 + length
            if item_end > end:
                raise DicomError("item overruns its container")
            _walk(data, pos + 8, item_end, depth + 1, None, until_item_delimiter=False)
            pos = item_end


def _walk(
    data: bytes,
    pos: int,
    end: int,
    depth: int,
    out: dict[tuple[int, int], tuple[int, int]] | None,
    *,
    until_item_delimiter: bool,
) -> int:
    """Walk Implicit VR LE elements. Top-level elements (out is not None) are
    recorded as tag -> (value offset, length); undefined-length sequences are
    descended and recorded with length -1."""
    previous = -1
    while pos < end:
        group, element, length = _header(data, pos, end)
        if group == 0xFFFE:
            if until_item_delimiter and element == 0xE00D:
                if length != 0:
                    raise DicomError("item delimiter with nonzero length")
                return pos + 8
            raise DicomError(f"unexpected delimiter ({group:04X},{element:04X}) at offset {pos}")
        key = (group << 16) | element
        if key <= previous:
            raise DicomError(f"tags not strictly ascending at offset {pos}")
        previous = key
        value_offset = pos + 8
        if length == 0xFFFFFFFF:
            if (group, element) == PIXEL_TAG:
                raise DicomError("encapsulated (undefined-length) Pixel Data")
            pos = _skip_undefined_sequence(data, value_offset, end, depth + 1)
            if out is not None:
                out[(group, element)] = (value_offset, -1)
            continue
        if value_offset + length > end:
            raise DicomError(f"element ({group:04X},{element:04X}) overruns the data")
        if out is not None:
            out[(group, element)] = (value_offset, length)
        pos = value_offset + length
    if until_item_delimiter:
        raise DicomError("missing item delimiter")
    return pos


def parse_dataset(data: bytes) -> tuple[dict[tuple[int, int], bytes], dict[tuple[int, int], tuple[int, int]], int]:
    meta, start = parse_meta(data)
    elements: dict[tuple[int, int], tuple[int, int]] = {}
    end = _walk(data, start, len(data), 0, elements, until_item_delimiter=False)
    if end != len(data):
        raise DicomError("dataset does not end at end of file")
    return meta, elements, start


class Instance:
    def __init__(self, data: bytes):
        self.data = data
        self.meta, self.elements, self.dataset_start = parse_dataset(data)

    def raw(self, tag: tuple[int, int]) -> bytes | None:
        entry = self.elements.get(tag)
        if entry is None:
            return None
        offset, length = entry
        if length < 0:
            raise DicomError(f"({tag[0]:04X},{tag[1]:04X}) is a sequence, not a value")
        return self.data[offset : offset + length]

    def text(self, tag: tuple[int, int]) -> str | None:
        value = self.raw(tag)
        if value is None:
            return None
        return value.decode("ascii", errors="strict").rstrip("\x00 ").strip()

    def require_text(self, tag: tuple[int, int]) -> str:
        value = self.text(tag)
        if value is None:
            raise DicomError(f"missing ({tag[0]:04X},{tag[1]:04X})")
        return value

    def us(self, tag: tuple[int, int]) -> int | None:
        value = self.raw(tag)
        if value is None:
            return None
        if len(value) != 2:
            raise DicomError(f"({tag[0]:04X},{tag[1]:04X}) is not a single US value")
        return struct.unpack("<H", value)[0]

    def require_us(self, tag: tuple[int, int]) -> int:
        value = self.us(tag)
        if value is None:
            raise DicomError(f"missing ({tag[0]:04X},{tag[1]:04X})")
        return value

    def fl(self, tag: tuple[int, int]) -> float | None:
        value = self.raw(tag)
        if value is None:
            return None
        if len(value) != 4:
            raise DicomError(f"({tag[0]:04X},{tag[1]:04X}) is not a single FL value")
        return struct.unpack("<f", value)[0]

    def meta_text(self, tag: tuple[int, int]) -> str:
        value = self.meta.get(tag)
        if value is None:
            raise DicomError(f"missing meta ({tag[0]:04X},{tag[1]:04X})")
        return value.decode("ascii").rstrip("\x00 ")


def pixel_values(pixel: bytes) -> array:
    values = array("H")
    values.frombytes(pixel)
    if sys.byteorder == "big":
        values.byteswap()
    return values


def validate_instance(
    data: bytes,
    *,
    patient: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Validate one DICOM-CT-PD Siemens full-dose projection view and return
    (Pixel Data bytes, metadata)."""
    if not MIN_FILE_BYTES <= len(data) <= MAX_FILE_BYTES:
        raise DicomError(f"file size {len(data)} outside [{MIN_FILE_BYTES}, {MAX_FILE_BYTES}]")
    inst = Instance(data)
    if inst.meta_text((0x0002, 0x0010)) != IMPLICIT_VR_LE:
        raise DicomError("transfer syntax is not Implicit VR Little Endian")
    if inst.meta_text((0x0002, 0x0002)) != RAW_DATA_SOP_CLASS:
        raise DicomError("media storage SOP class is not Raw Data Storage")
    expected_text = {
        T_SOP_CLASS: RAW_DATA_SOP_CLASS,
        T_MODALITY: "CT",
        T_MANUFACTURER: "SIEMENS",
        T_SERIES_DESCRIPTION: "Full dose projections",
        T_PHOTOMETRIC: "MONOCHROME2",
        T_DET_SHAPE: "CYLINDRICAL",
        T_PROJECTION_TYPE: "HELICAL",
        T_PROJECTION_GEOMETRY: "FANBEAM",
    }
    for tag, expected in expected_text.items():
        if inst.text(tag) != expected:
            raise DicomError(f"({tag[0]:04X},{tag[1]:04X}) = {inst.text(tag)!r}, expected {expected!r}")
    for group in PRIVATE_GROUPS:
        if inst.text((group, 0x0010)) != MAYO_CREATOR:
            raise DicomError(f"private creator ({group:04X},0010) is not {MAYO_CREATOR!r}")
    for tag in T_PREPROCESSING_FLAGS:
        if inst.text(tag) != "YES":
            raise DicomError(f"preprocessing flag ({tag[0]:04X},{tag[1]:04X}) is not YES")
    sop = inst.require_text(T_SOP_INSTANCE)
    if inst.meta_text((0x0002, 0x0003)) != sop or not UID_RE.fullmatch(sop):
        raise DicomError("SOP instance UID mismatch between meta and dataset")
    series = inst.require_text(T_SERIES_UID)
    pid = inst.require_text(T_PATIENT_ID)
    if sop_uid is not None and sop != sop_uid:
        raise DicomError(f"SOP instance UID {sop} != requested {sop_uid}")
    if series_uid is not None and series != series_uid:
        raise DicomError(f"series UID {series} != requested {series_uid}")
    if patient is not None and pid != patient:
        raise DicomError(f"patient {pid} != requested {patient}")
    if not re.fullmatch(r"[CL][0-9]{3}", pid):
        raise DicomError(f"patient {pid!r} is not a public chest/liver subject")
    body_part = inst.require_text(T_BODY_PART)
    if body_part != BODY_PART[pid[0]]:
        raise DicomError(f"body part {body_part!r} unexpected for {pid}")
    expected_us = {
        T_SAMPLES_PER_PIXEL: 1,
        T_ROWS: ROWS,
        T_COLUMNS: COLUMNS,
        T_BITS_ALLOCATED: 16,
        T_BITS_STORED: 16,
        T_HIGH_BIT: 15,
        T_PIXEL_REPRESENTATION: 0,
        T_DET_ROWS: COLUMNS,
        T_DET_COLUMNS: ROWS,
    }
    for tag, expected in expected_us.items():
        if inst.require_us(tag) != expected:
            raise DicomError(f"({tag[0]:04X},{tag[1]:04X}) = {inst.us(tag)}, expected {expected}")
    instance_number = int(inst.require_text(T_INSTANCE_NUMBER))
    if instance_number <= 0:
        raise DicomError("non-positive InstanceNumber")
    slope_text = inst.require_text(T_RESCALE_SLOPE)
    intercept_text = inst.require_text(T_RESCALE_INTERCEPT)
    slope = float(slope_text)
    intercept = float(intercept_text)
    if not (math.isfinite(slope) and 0 < slope < 1e-2 and math.isfinite(intercept) and abs(intercept) < 10):
        raise DicomError(f"implausible rescale slope/intercept {slope_text}/{intercept_text}")
    pixel_entry = inst.elements.get(PIXEL_TAG)
    if pixel_entry is None:
        raise DicomError("missing Pixel Data")
    offset, length = pixel_entry
    if length != PIXEL_BYTES:
        raise DicomError(f"Pixel Data length {length} != {PIXEL_BYTES}")
    if offset + length != len(data) or max(inst.elements) != PIXEL_TAG:
        raise DicomError("Pixel Data is not the final element")
    pixel = data[offset : offset + length]
    values = pixel_values(pixel)
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        raise DicomError("constant projection view")
    smallest = inst.us(T_SMALLEST)
    largest = inst.us(T_LARGEST)
    if smallest is not None and smallest != minimum:
        raise DicomError(f"SmallestImagePixelValue {smallest} != decoded minimum {minimum}")
    if largest is not None and largest != maximum:
        raise DicomError(f"LargestImagePixelValue {largest} != decoded maximum {maximum}")
    kvp_text = inst.text(T_KVP)
    current_text = inst.text(T_TUBE_CURRENT)
    info: dict[str, object] = {
        "patient_id": pid,
        "body_part": body_part,
        "series_instance_uid": series,
        "sop_instance_uid": sop,
        "instance_number": instance_number,
        "kvp": float(kvp_text) if kvp_text else None,
        "xray_tube_current_ma": float(current_text) if current_text else None,
        "rescale_slope": slope_text,
        "rescale_intercept": intercept_text,
        "flying_focal_spot_mode": inst.text(T_FFS_MODE),
        "source_angular_steps_per_rotation": inst.us(T_ANGULAR_STEPS),
        "detector_focal_center_angular_position_rad": inst.fl(T_ANGULAR_POSITION),
        "detector_focal_center_axial_position_mm": inst.fl(T_AXIAL_POSITION),
        "water_attenuation_coefficient_per_mm": inst.text(T_WATER_MU),
        "pixel_data_offset": offset,
        "min": minimum,
        "max": maximum,
    }
    return pixel, info


# --------------------------------------------------------------------------
# Synthetic self-test
# --------------------------------------------------------------------------

def _explicit(group: int, element: int, vr: bytes, value: bytes) -> bytes:
    if vr in (b"OB", b"OW", b"SQ", b"UN"):
        return struct.pack("<HH2sHI", group, element, vr, 0, len(value)) + value
    return struct.pack("<HH2sH", group, element, vr, len(value)) + value


def _even(value: bytes, pad: bytes = b" ") -> bytes:
    return value + pad if len(value) % 2 else value


def _implicit(group: int, element: int, value: bytes, length: int | None = None) -> bytes:
    return struct.pack("<HHI", group, element, len(value) if length is None else length) + value


def synthetic_instance(
    *,
    mutate: str = "",
    values: array | None = None,
    patient: str = "C999",
    series: str = "1.2.3.4.5.7",
    sop: str = "1.2.3.4.5.6",
    instance_number: int = 4301,
) -> bytes:
    if values is None:
        values = array("H", ((index * 7919 + (index // 64) * 13) % 40000 + 500 for index in range(VALUE_COUNT)))
    le_values = array("H", values)
    if sys.byteorder == "big":
        le_values.byteswap()
    pixel = le_values.tobytes()
    ts = IMPLICIT_VR_LE if mutate != "explicit_ts" else "1.2.840.10008.1.2.1"
    meta_body = (
        _explicit(0x0002, 0x0001, b"OB", b"\x00\x01")
        + _explicit(0x0002, 0x0002, b"UI", _even(RAW_DATA_SOP_CLASS.encode(), b"\x00"))
        + _explicit(0x0002, 0x0003, b"UI", _even(sop.encode(), b"\x00"))
        + _explicit(0x0002, 0x0010, b"UI", _even(ts.encode(), b"\x00"))
    )
    meta = _explicit(0x0002, 0x0000, b"UL", struct.pack("<I", len(meta_body))) + meta_body
    nested_defined_item = _implicit(0x0008, 0x0100, _even(b"CODE1"))
    nested_sequence_defined = _implicit(0xFFFE, 0xE000, nested_defined_item)
    undefined_item_body = (
        _implicit(0x0008, 0x0100, _even(b"X1"))
        # nested defined-length sequence: skipped by length, never descended
        + _implicit(0x0040, 0xA043, nested_sequence_defined)
        # nested undefined-length sequence with one defined-length item
        + _implicit(0x0040, 0xA730, b"", 0xFFFFFFFF)
        + nested_sequence_defined
        + _implicit(0xFFFE, 0xE0DD, b"")
    )
    undefined_sequence = (
        _implicit(0x0040, 0x0275, b"", 0xFFFFFFFF)
        + _implicit(0xFFFE, 0xE000, b"", 0xFFFFFFFF)
        + undefined_item_body
        + _implicit(0xFFFE, 0xE00D, b"")
    )
    if mutate != "missing_seq_delim":
        undefined_sequence += _implicit(0xFFFE, 0xE0DD, b"")
    minimum = min(values)
    maximum = max(values)
    rows_value = ROWS if mutate != "rows" else 512
    elements = [
        _implicit(0x0008, 0x0016, _even(RAW_DATA_SOP_CLASS.encode(), b"\x00")),
        _implicit(0x0008, 0x0018, _even(sop.encode(), b"\x00")),
        _implicit(0x0008, 0x0060, b"CT"),
        _implicit(0x0008, 0x0070, b"SIEMENS "),
        _implicit(0x0008, 0x103E, _even(b"Full dose projections")),
        _implicit(0x0010, 0x0020, _even(patient.encode())),
        _implicit(0x0018, 0x0015, _even(BODY_PART[patient[0]].encode())),
        _implicit(0x0018, 0x0060, b"120 "),
        _implicit(0x0018, 0x1151, b"230 "),
        _implicit(0x0020, 0x000E, _even(series.encode(), b"\x00")),
        _implicit(0x0020, 0x0013, _even(str(instance_number).encode())),
        _implicit(0x0028, 0x0002, struct.pack("<H", 1)),
        _implicit(0x0028, 0x0004, b"MONOCHROME2 "),
        _implicit(0x0028, 0x0010, struct.pack("<H", rows_value)),
        _implicit(0x0028, 0x0011, struct.pack("<H", COLUMNS)),
        _implicit(0x0028, 0x0100, struct.pack("<H", 16)),
        _implicit(0x0028, 0x0101, struct.pack("<H", 16)),
        _implicit(0x0028, 0x0102, struct.pack("<H", 15)),
        _implicit(0x0028, 0x0103, struct.pack("<H", 0)),
        _implicit(0x0028, 0x0106, struct.pack("<H", minimum)),
        _implicit(0x0028, 0x0107, struct.pack("<H", maximum + (1 if mutate == "largest" else 0))),
        _implicit(0x0028, 0x1052, _even(b"-0.1977421025986")),
        _implicit(0x0028, 0x1053, _even(b"0.00019311177675")),
        undefined_sequence,
        _implicit(0x0040, 0x0555, b"", 0xFFFFFFFF) + _implicit(0xFFFE, 0xE0DD, b""),
    ]
    for group in PRIVATE_GROUPS:
        elements.append(_implicit(group, 0x0010, _even(MAYO_CREATOR.encode())))
        if group == 0x7029:
            elements.append(_implicit(group, 0x100B, b"CYLINDRICAL "))
            elements.append(_implicit(group, 0x1010, struct.pack("<H", COLUMNS)))
            elements.append(_implicit(group, 0x1011, struct.pack("<H", ROWS)))
        elif group == 0x7031:
            elements.append(_implicit(group, 0x1001, struct.pack("<f", 2.25)))
            elements.append(_implicit(group, 0x1002, struct.pack("<f", 148.5)))
        elif group == 0x7033:
            elements.append(_implicit(group, 0x100E, b"FFSZ"))
            elements.append(_implicit(group, 0x1013, struct.pack("<H", 1152)))
            # PhotonStatistics: one float per detector column, as in real objects.
            elements.append(_implicit(group, 0x1065, struct.pack(f"<{ROWS}f", *([10000.0] * ROWS))))
        elif group == 0x7037:
            elements.append(_implicit(group, 0x1009, b"HELICAL "))
            elements.append(_implicit(group, 0x100A, b"FANBEAM "))
        elif group == 0x7039:
            for element in range(0x1003, 0x100A):
                flag = b"NO  " if (mutate == "log_flag" and element == 0x1009) else b"YES "
                elements.append(_implicit(group, element, flag))
        elif group == 0x7041:
            elements.append(_implicit(group, 0x1001, b"0.0192"))
    if mutate == "encapsulated":
        elements.append(_implicit(0x7FE0, 0x0010, b"", 0xFFFFFFFF) + _implicit(0xFFFE, 0xE0DD, b""))
        elements.append(b"\x00" * (PIXEL_BYTES - 16))
    else:
        elements.append(_implicit(0x7FE0, 0x0010, pixel))
    if mutate == "trailing":
        elements.append(_implicit(0xFFFC, 0xFFFC, b"\x00\x00"))
    if mutate == "unsorted":
        elements[3], elements[4] = elements[4], elements[3]
    data = b"\x00" * 128 + b"DICM" + meta + b"".join(elements)
    if mutate == "truncated":
        data = data[:-100]
    return data


def selftest() -> None:
    values = array("H", ((index * 7919 + (index // 64) * 13) % 40000 + 500 for index in range(VALUE_COUNT)))
    data = synthetic_instance(values=values)
    pixel, info = validate_instance(data, patient="C999", series_uid="1.2.3.4.5.7", sop_uid="1.2.3.4.5.6")
    if pixel_values(pixel) != values:
        raise SystemExit("selftest: decoded pixels differ from synthetic input")
    expected = {
        "instance_number": 4301,
        "rescale_slope": "0.00019311177675",
        "rescale_intercept": "-0.1977421025986",
        "flying_focal_spot_mode": "FFSZ",
        "source_angular_steps_per_rotation": 1152,
        "min": min(values),
        "max": max(values),
        "kvp": 120.0,
    }
    for key, value in expected.items():
        if info[key] != value:
            raise SystemExit(f"selftest: {key} = {info[key]!r}, expected {value!r}")
    if pixel[:2] != struct.pack("<H", values[0]) or data[-PIXEL_BYTES - 8 : -PIXEL_BYTES] != PIXEL_HEADER:
        raise SystemExit("selftest: little-endian pixel layout mismatch")
    for mutate in ("explicit_ts", "missing_seq_delim", "rows", "largest", "encapsulated", "trailing", "unsorted", "truncated", "log_flag"):
        try:
            validate_instance(synthetic_instance(mutate=mutate, values=values))
        except (DicomError, struct.error, UnicodeDecodeError, ValueError):
            continue
        raise SystemExit(f"selftest: corrupted variant {mutate!r} was accepted")
    try:
        validate_instance(synthetic_instance(values=array("H", [1000]) * VALUE_COUNT))
    except DicomError:
        pass
    else:
        raise SystemExit("selftest: constant view was accepted")
    print("selftest=ok synthetic_valid=1 synthetic_rejected=10")


# --------------------------------------------------------------------------
# Pins, listings and selection
# --------------------------------------------------------------------------

def read_pins(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    expected = ["patient_id", "body_part", "series_instance_uid", "study_instance_uid", "image_count", "file_size_bytes"]
    if header != expected:
        raise SystemExit(f"unexpected pins header {header}")
    pins = []
    for line in lines[1:]:
        fields = dict(zip(header, line.split("\t")))
        fields["image_count"] = int(fields["image_count"])
        fields["file_size_bytes"] = int(fields["file_size_bytes"])
        pins.append(fields)
    patients = [pin["patient_id"] for pin in pins]
    if len(pins) != EXPECTED_SERIES or len(set(patients)) != EXPECTED_SERIES or patients != sorted(patients):
        raise SystemExit("series pins must list 100 distinct sorted patients")
    if sum(1 for pin in pins if str(pin["patient_id"]).startswith("C")) != 50:
        raise SystemExit("series pins must list 50 chest and 50 liver subjects")
    for pin in pins:
        if not re.fullmatch(r"[CL][0-9]{3}", str(pin["patient_id"])) or pin["body_part"] != BODY_PART[str(pin["patient_id"])[0]]:
            raise SystemExit(f"bad pin row {pin}")
    return pins


def check_series(listing: Path, pins_path: Path) -> None:
    rows = json.loads(listing.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise SystemExit("getSeries listing is not a non-empty JSON array")
    pins = read_pins(pins_path)
    by_uid = {}
    for row in rows:
        uid = str(row.get("SeriesInstanceUID", ""))
        if uid in by_uid:
            raise SystemExit(f"duplicate series row {uid}")
        by_uid[uid] = row
    live_siemens_full = {
        uid for uid, row in by_uid.items()
        if row.get("Manufacturer") == "SIEMENS" and row.get("SeriesDescription") == "Full dose projections"
    }
    for pin in pins:
        row = by_uid.get(str(pin["series_instance_uid"]))
        if row is None:
            raise SystemExit(f"pinned series missing from live listing: {pin['patient_id']}")
        expected = {
            "Collection": COLLECTION,
            "Modality": "CT",
            "Manufacturer": "SIEMENS",
            "SeriesDescription": "Full dose projections",
            "PatientID": pin["patient_id"],
            "BodyPartExamined": pin["body_part"],
            "StudyInstanceUID": pin["study_instance_uid"],
            "ImageCount": pin["image_count"],
            "FileSize": pin["file_size_bytes"],
            "LicenseURI": LICENSE_URI,
            "LicenseName": LICENSE_NAME,
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise SystemExit(f"{pin['patient_id']}: live {key} {row.get(key)!r} != pinned {value!r}")
    extras = sorted(live_siemens_full - {str(pin["series_instance_uid"]) for pin in pins})
    print(
        f"series_validation=ok listing_rows={len(rows)} pinned_series={len(pins)} "
        f"pinned_instances={sum(int(pin['image_count']) for pin in pins)} license=CC-BY-4.0 "
        f"unpinned_siemens_full_dose_series={len(extras)}"
    )


def load_sop_list(path: Path, count: int) -> list[str]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{path.name}: unreadable SOP listing: {exc}")
    if not isinstance(rows, list):
        raise SystemExit(f"{path.name}: SOP listing is not a JSON array")
    uids = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"SOPInstanceUID"}:
            raise SystemExit(f"{path.name}: unexpected SOP listing row {row!r}")
        uid = str(row["SOPInstanceUID"])
        if not UID_RE.fullmatch(uid) or len(uid) > 64:
            raise SystemExit(f"{path.name}: invalid SOP UID {uid!r}")
        uids.append(uid)
    if len(uids) != count or len(set(uids)) != count:
        raise SystemExit(f"{path.name}: {len(uids)} UIDs ({len(set(uids))} distinct), expected {count}")
    return uids


def select_ranks(count: int, per_series: int = PER_SERIES) -> list[int]:
    """Evenly spaced midpoint ranks over the lexicographically sorted UIDs."""
    return [((2 * index + 1) * count) // (2 * per_series) for index in range(per_series)]


def derive_selection(pins: list[dict[str, object]], sop_dir: Path) -> list[dict[str, object]]:
    selection = []
    for pin in pins:
        uids = sorted(load_sop_list(sop_dir / f"{pin['patient_id']}.json", int(pin["image_count"])))
        for rank in select_ranks(len(uids)):
            selection.append({
                "patient_id": pin["patient_id"],
                "series_instance_uid": pin["series_instance_uid"],
                "rank": rank,
                "sop_instance_uid": uids[rank],
            })
    return selection


SELECTION_HEADER = ["patient_id", "series_instance_uid", "rank", "sop_instance_uid"]


def write_selection(path: Path, selection: list[dict[str, object]]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(SELECTION_HEADER) + "\n")
        for row in selection:
            handle.write("\t".join(str(row[key]) for key in SELECTION_HEADER) + "\n")
    temporary.replace(path)


def read_selection(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines[0].split("\t") != SELECTION_HEADER:
        raise SystemExit("unexpected selection header")
    rows = []
    for line in lines[1:]:
        row = dict(zip(SELECTION_HEADER, line.split("\t")))
        row["rank"] = int(row["rank"])
        rows.append(row)
    return rows


def instance_path(download_dir: Path, row: dict[str, object]) -> Path:
    return download_dir / "dicom" / str(row["patient_id"]) / f"{row['sop_instance_uid']}.dcm"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Build and verify
# --------------------------------------------------------------------------

def load_inputs(download_dir: Path, pins_path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], dict]:
    pins = read_pins(pins_path)
    selection = read_selection(download_dir / "selection.tsv")
    inventory = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    if len(selection) != EXPECTED_SERIES * PER_SERIES:
        raise SystemExit(f"selection has {len(selection)} rows, expected {EXPECTED_SERIES * PER_SERIES}")
    if inventory.get("instances") != len(selection):
        raise SystemExit("download inventory does not match the selection")
    return pins, selection, inventory


def sample_name(info: dict[str, object]) -> str:
    return f"{info['patient_id']}_i{int(info['instance_number']):06d}.bin"


def summarize(rows: list[dict[str, object]], pins: list[dict[str, object]]) -> dict[str, object]:
    per_series = []
    for pin in pins:
        series_rows = [row for row in rows if row["patient_id"] == pin["patient_id"]]
        per_series.append({
            "patient_id": pin["patient_id"],
            "body_part": pin["body_part"],
            "series_instance_uid": pin["series_instance_uid"],
            "series_image_count": pin["image_count"],
            "samples": len(series_rows),
            "rescale_slope": sorted({row["rescale_slope"] for row in series_rows}),
            "rescale_intercept": sorted({row["rescale_intercept"] for row in series_rows}),
            "kvp": sorted({row["kvp"] for row in series_rows}),
            "flying_focal_spot_mode": sorted({str(row["flying_focal_spot_mode"]) for row in series_rows}),
            "source_angular_steps_per_rotation": sorted({int(row["source_angular_steps_per_rotation"] or 0) for row in series_rows}),
            "instance_number_min": min(int(row["instance_number"]) for row in series_rows),
            "instance_number_max": max(int(row["instance_number"]) for row in series_rows),
            "min": min(int(row["min"]) for row in series_rows),
            "max": max(int(row["max"]) for row in series_rows),
        })
    slopes = [float(entry["rescale_slope"][0]) for entry in per_series]
    count = lambda key: {str(value): sum(1 for row in rows if str(row[key]) == str(value)) for value in sorted({str(row[key]) for row in rows})}
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(rows),
        "values": len(rows) * VALUE_COUNT,
        "bytes": len(rows) * PIXEL_BYTES,
        "sample_shape": [ROWS, COLUMNS],
        "global_min": min(int(row["min"]) for row in rows),
        "global_max": max(int(row["max"]) for row in rows),
        "distinct_values_per_view_min": min(int(row["distinct_values"]) for row in rows),
        "distinct_values_per_view_median": sorted(int(row["distinct_values"]) for row in rows)[len(rows) // 2],
        "rescale_slope_min": min(slopes),
        "rescale_slope_max": max(slopes),
        "samples_by_body_part": count("body_part"),
        "samples_by_kvp": count("kvp"),
        "samples_by_flying_focal_spot_mode": count("flying_focal_spot_mode"),
        "samples_by_source_angular_steps": count("source_angular_steps_per_rotation"),
        "per_series": per_series,
    }


def index_row(data_root: Path, path: Path, pixel: bytes, info: dict[str, object], rank: int, source_sha256: str) -> dict[str, object]:
    values = pixel_values(pixel)
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": path.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": len(pixel),
        "value_count": len(values),
        "sample_shape": [ROWS, COLUMNS],
        "sample_axes": ["detector_column_channel", "detector_row"],
        "min": min(values),
        "max": max(values),
        "distinct_values": len(set(values)),
        "sha256": sha256_bytes(pixel),
        "patient_id": info["patient_id"],
        "body_part": info["body_part"],
        "series_instance_uid": info["series_instance_uid"],
        "sop_instance_uid": info["sop_instance_uid"],
        "selection_rank": rank,
        "instance_number": info["instance_number"],
        "kvp": info["kvp"],
        "xray_tube_current_ma": info["xray_tube_current_ma"],
        "rescale_slope": info["rescale_slope"],
        "rescale_intercept": info["rescale_intercept"],
        "flying_focal_spot_mode": info["flying_focal_spot_mode"],
        "source_angular_steps_per_rotation": info["source_angular_steps_per_rotation"],
        "detector_focal_center_angular_position_rad": info["detector_focal_center_angular_position_rad"],
        "detector_focal_center_axial_position_mm": info["detector_focal_center_axial_position_mm"],
        "source_file_sha256": source_sha256,
    }


def build(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    samples_dir = Path(args.samples_dir)
    pins, selection, inventory = load_inputs(download_dir, Path(args.pins))
    inventory_by_sop = {record["sop_instance_uid"]: record for record in inventory["records"]}
    samples_dir.mkdir(parents=True, exist_ok=True)
    for stale in samples_dir.glob("*.bin"):
        stale.unlink()
    rows = []
    names = set()
    for row in selection:
        data = instance_path(download_dir, row).read_bytes()
        record = inventory_by_sop.get(str(row["sop_instance_uid"]))
        source_sha256 = sha256_bytes(data)
        if record is None or record["bytes"] != len(data) or record["sha256"] != source_sha256:
            raise SystemExit(f"{row['sop_instance_uid']}: source file differs from download inventory")
        pixel, info = validate_instance(
            data,
            patient=str(row["patient_id"]),
            series_uid=str(row["series_instance_uid"]),
            sop_uid=str(row["sop_instance_uid"]),
        )
        name = sample_name(info)
        if name in names:
            raise SystemExit(f"duplicate InstanceNumber within series: {name}")
        names.add(name)
        output = samples_dir / name
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_bytes(pixel)
        temporary.replace(output)
        entry = index_row(data_root, output, pixel, info, int(row["rank"]), source_sha256)
        if entry["distinct_values"] < MIN_DISTINCT_VALUES:
            raise SystemExit(f"{name}: only {entry['distinct_values']} distinct values")
        rows.append(entry)
    rows.sort(key=lambda entry: (entry["patient_id"], entry["instance_number"]))
    stats = summarize(rows, pins)
    for entry in stats["per_series"]:
        if entry["samples"] != PER_SERIES:
            raise SystemExit(f"{entry['patient_id']}: {entry['samples']} samples, expected {PER_SERIES}")
        if len(entry["rescale_slope"]) != 1 or len(entry["rescale_intercept"]) != 1:
            raise SystemExit(f"{entry['patient_id']}: rescale slope/intercept not constant within series")
    index_path = Path(args.index)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = index_path.with_name(index_path.name + ".tmp")
    temporary.write_text("".join(json.dumps(entry, sort_keys=True) + "\n" for entry in rows), encoding="utf-8")
    temporary.replace(index_path)
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"build=ok samples={stats['samples']} bytes={stats['bytes']} values={stats['values']} "
        f"range={stats['global_min']}..{stats['global_max']} slope={stats['rescale_slope_min']:.6g}..{stats['rescale_slope_max']:.6g} "
        f"body_parts={stats['samples_by_body_part']} kvp={stats['samples_by_kvp']}"
    )


def verify(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    samples_dir = Path(args.samples_dir)
    pins, selection, inventory = load_inputs(download_dir, Path(args.pins))
    # 1. Re-derive the selection from the cached SOP listings.
    derived = derive_selection(pins, download_dir / "sop_lists")
    if [(r["patient_id"], r["series_instance_uid"], r["rank"], r["sop_instance_uid"]) for r in derived] != [
        (r["patient_id"], r["series_instance_uid"], r["rank"], r["sop_instance_uid"]) for r in selection
    ]:
        raise SystemExit("selection.tsv does not match the selection re-derived from the SOP listings")
    # 2. Re-parse every source object and compare against the emitted samples.
    index_rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {row["sample_path"]: row for row in index_rows}
    if len(by_path) != len(index_rows) or len(index_rows) != len(selection):
        raise SystemExit(f"index rows {len(index_rows)} != selection {len(selection)} or duplicate paths")
    inventory_by_sop = {record["sop_instance_uid"]: record for record in inventory["records"]}
    expected_paths = set()
    recomputed = []
    for row in selection:
        data = instance_path(download_dir, row).read_bytes()
        record = inventory_by_sop[str(row["sop_instance_uid"])]
        source_sha256 = sha256_bytes(data)
        if record["bytes"] != len(data) or record["sha256"] != source_sha256:
            raise SystemExit(f"{row['sop_instance_uid']}: source differs from download inventory")
        pixel, info = validate_instance(
            data,
            patient=str(row["patient_id"]),
            series_uid=str(row["series_instance_uid"]),
            sop_uid=str(row["sop_instance_uid"]),
        )
        # Independent location check: Pixel Data is the trailing fixed-size element.
        if data[-(PIXEL_BYTES + 8) : -PIXEL_BYTES] != PIXEL_HEADER or data[-PIXEL_BYTES:] != pixel:
            raise SystemExit(f"{row['sop_instance_uid']}: trailing Pixel Data element mismatch")
        output = samples_dir / sample_name(info)
        relative = output.relative_to(data_root).as_posix()
        expected_paths.add(relative)
        if output.read_bytes() != pixel:
            raise SystemExit(f"{relative}: sample bytes differ from source Pixel Data")
        expected = index_row(data_root, output, pixel, info, int(row["rank"]), source_sha256)
        actual = by_path.get(relative)
        if actual != json.loads(json.dumps(expected)):
            raise SystemExit(f"{relative}: index row mismatch")
        if expected["distinct_values"] < MIN_DISTINCT_VALUES or expected["min"] == expected["max"]:
            raise SystemExit(f"{relative}: degenerate projection view")
        recomputed.append(expected)
    actual_files = {path.relative_to(data_root).as_posix() for path in samples_dir.glob("*")}
    if actual_files != expected_paths:
        raise SystemExit(f"sample directory mismatch: extra={sorted(actual_files - expected_paths)[:5]} missing={sorted(expected_paths - actual_files)[:5]}")
    recomputed.sort(key=lambda entry: (entry["patient_id"], entry["instance_number"]))
    stats = summarize(recomputed, pins)
    for entry in stats["per_series"]:
        if entry["samples"] != PER_SERIES or len(entry["rescale_slope"]) != 1:
            raise SystemExit(f"{entry['patient_id']}: per-series coverage or rescale check failed")
    if stats["samples_by_body_part"] != {"ABDOMEN": 1000, "CHEST": 1000}:
        raise SystemExit(f"unexpected body-part split {stats['samples_by_body_part']}")
    stored = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if stored != json.loads(json.dumps(stats)):
        raise SystemExit("ingest_stats.json differs from recomputed statistics")
    # 3. Manifest claims must match realized output.
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [entry for entry in manifest["series"] if entry["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("manifest primary series missing")
    if series[0]["sample_count"] != stats["samples"] or series[0]["total_size_bytes"] != stats["bytes"]:
        raise SystemExit("manifest sample_count/total_size_bytes do not match realized output")
    print(
        f"verify=ok samples={stats['samples']} bytes={stats['bytes']} series={len(stats['per_series'])} "
        f"range={stats['global_min']}..{stats['global_max']} min_distinct_per_view={stats['distinct_values_per_view_min']}"
    )


def inventory(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    pins = read_pins(Path(args.pins))
    selection = read_selection(download_dir / "selection.tsv")
    derived = derive_selection(pins, download_dir / "sop_lists")
    if [(r["sop_instance_uid"], r["rank"]) for r in derived] != [(r["sop_instance_uid"], r["rank"]) for r in selection]:
        raise SystemExit("selection.tsv is stale relative to the SOP listings")
    records = []
    total = 0
    for row in selection:
        path = instance_path(download_dir, row)
        data = path.read_bytes()
        _, info = validate_instance(
            data,
            patient=str(row["patient_id"]),
            series_uid=str(row["series_instance_uid"]),
            sop_uid=str(row["sop_instance_uid"]),
        )
        total += len(data)
        records.append({
            "patient_id": row["patient_id"],
            "sop_instance_uid": row["sop_instance_uid"],
            "instance_number": info["instance_number"],
            "bytes": len(data),
            "sha256": sha256_bytes(data),
        })
    payload = {
        "dataset_id": DATASET_ID,
        "instances": len(records),
        "dicom_bytes": total,
        "records": records,
    }
    target = download_dir / "download_inventory.json"
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    print(f"inventory=ok instances={len(records)} dicom_bytes={total}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest")
    p = sub.add_parser("check-series")
    p.add_argument("--listing", required=True)
    p.add_argument("--pins", required=True)
    p = sub.add_parser("check-sops")
    p.add_argument("--file", required=True)
    p.add_argument("--count", type=int, required=True)
    p = sub.add_parser("select")
    p.add_argument("--pins", required=True)
    p.add_argument("--sop-dir", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("check-instance")
    p.add_argument("--file", required=True)
    p.add_argument("--patient", required=True)
    p.add_argument("--series", required=True)
    p.add_argument("--sop", required=True)
    for name in ("inventory", "build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", required=True)
        p.add_argument("--pins", required=True)
        if name != "inventory":
            p.add_argument("--data-root", required=True)
            p.add_argument("--samples-dir", required=True)
            p.add_argument("--index", required=True)
            p.add_argument("--stats", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.command == "selftest":
        selftest()
    elif args.command == "check-series":
        check_series(Path(args.listing), Path(args.pins))
    elif args.command == "check-sops":
        uids = load_sop_list(Path(args.file), args.count)
        print(f"sop_listing=ok file={Path(args.file).name} uids={len(uids)}")
    elif args.command == "select":
        selection = derive_selection(read_pins(Path(args.pins)), Path(args.sop_dir))
        write_selection(Path(args.out), selection)
        print(f"selection=ok rows={len(selection)} per_series={PER_SERIES}")
    elif args.command == "check-instance":
        try:
            _, info = validate_instance(
                Path(args.file).read_bytes(), patient=args.patient, series_uid=args.series, sop_uid=args.sop
            )
        except (DicomError, struct.error, UnicodeDecodeError, ValueError) as exc:
            print(f"instance_invalid file={Path(args.file).name} reason={exc}", file=sys.stderr)
            return 3
        print(f"instance=ok patient={info['patient_id']} instance_number={info['instance_number']} range={info['min']}..{info['max']}")
    elif args.command == "inventory":
        inventory(args)
    elif args.command == "build":
        build(args)
    elif args.command == "verify":
        verify(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
