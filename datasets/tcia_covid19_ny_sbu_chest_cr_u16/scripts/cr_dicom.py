#!/usr/bin/env python3
"""Pure-stdlib DICOM header walker and pixel extractor for the pinned
COVID-19-NY-SBU Carestream DRX-Revolution chest CR objects.

Subcommands:
  validate  check one downloaded DICOM file against its pinned row (download.sh)
  build     emit one raw little-endian uint16 Pixel Data plane per pinned image
  verify    independently re-derive every sample, index row and statistic
  selftest  exercise the walker on synthetic DICOM streams
"""
from __future__ import annotations

import argparse
from array import array
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys
import tomllib

DATASET_ID = "tcia_covid19_ny_sbu_chest_cr_u16"
SERIES_ID = "sbu_chest_cr_pixel_u16"
TRANSFER_SYNTAX = "1.2.840.10008.1.2.1"
CR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.1"
ROWS = 2544
COLUMNS = 3056
VALUES_PER_IMAGE = ROWS * COLUMNS
PIXEL_BYTES = VALUES_PER_IMAGE * 2
BITS_STORED = 12
MAX_STORED_VALUE = (1 << BITS_STORED) - 1
EXPECTED_IMAGES = 48
SOFTWARE_VERSIONS = {"5.7.712.6007", "5.7.712.7009", "5.7.712.8007"}
PIN_COLUMNS = [
    "ordinal",
    "patient_id",
    "study_instance_uid",
    "series_instance_uid",
    "sop_instance_uid",
    "file_size",
    "header_bytes",
    "header_sha256",
    "software_versions",
    "study_desc",
]

ITEM = (0xFFFE, 0xE000)
ITEM_DELIMITER = (0xFFFE, 0xE00D)
SEQUENCE_DELIMITER = (0xFFFE, 0xE0DD)
PIXEL_DATA = (0x7FE0, 0x0010)
UNDEFINED = 0xFFFFFFFF
LONG_VR = {b"OB", b"OD", b"OF", b"OL", b"OV", b"OW", b"SQ", b"SV", b"UC", b"UR", b"UT", b"UN", b"UV"}
MAX_DEPTH = 16


class DicomError(ValueError):
    pass


# --------------------------------------------------------------------------
# Header walker
# --------------------------------------------------------------------------

def _element_header(data: bytes, offset: int) -> tuple[tuple[int, int], bytes, int, int]:
    if offset + 8 > len(data):
        raise DicomError(f"truncated element header at {offset}")
    group, element = struct.unpack_from("<HH", data, offset)
    vr = data[offset + 4:offset + 6]
    if len(vr) != 2 or not all(65 <= byte <= 90 for byte in vr):
        raise DicomError(f"invalid explicit VR {vr!r} at {offset} for tag ({group:04X},{element:04X})")
    if vr in LONG_VR:
        if offset + 12 > len(data):
            raise DicomError(f"truncated long element header at {offset}")
        if data[offset + 6:offset + 8] != b"\0\0":
            raise DicomError(f"nonzero reserved bytes at {offset}")
        return (group, element), vr, struct.unpack_from("<I", data, offset + 8)[0], offset + 12
    return (group, element), vr, struct.unpack_from("<H", data, offset + 6)[0], offset + 8


def _walk_items(data: bytes, value_offset: int, length: int, depth: int) -> int:
    """Skip a sequence value (defined or undefined length); return the end offset."""
    if depth > MAX_DEPTH:
        raise DicomError("sequence nesting too deep")
    position = value_offset
    end = value_offset + length if length != UNDEFINED else None
    if end is not None and end > len(data):
        raise DicomError("sequence extends past available data")
    while True:
        if end is not None and position == end:
            return position
        if end is not None and position > end:
            raise DicomError("sequence items overrun the sequence length")
        if position + 8 > len(data):
            raise DicomError("truncated sequence")
        tag = struct.unpack_from("<HH", data, position)
        item_length = struct.unpack_from("<I", data, position + 4)[0]
        if tag == SEQUENCE_DELIMITER:
            if end is not None or item_length != 0:
                raise DicomError("unexpected sequence delimiter")
            return position + 8
        if tag != ITEM:
            raise DicomError(f"expected item tag in sequence at {position}, got {tag}")
        position += 8
        if item_length == UNDEFINED:
            position, reason = _walk(data, position, len(data), depth, None)
            if reason != "item_end":
                raise DicomError("undefined-length item without delimiter")
        else:
            item_end = position + item_length
            if item_end > len(data):
                raise DicomError("item extends past available data")
            stop, reason = _walk(data, position, item_end, depth, None)
            if reason != "end" or stop != item_end:
                raise DicomError("defined-length item does not end at its boundary")
            position = item_end


def _walk(
    data: bytes, offset: int, end: int, depth: int, top: dict | None
) -> tuple[int, str]:
    previous = None
    while offset < end:
        if offset + 8 > len(data):
            raise DicomError(f"truncated element at {offset}")
        tag = struct.unpack_from("<HH", data, offset)
        if tag == ITEM_DELIMITER:
            if top is not None or struct.unpack_from("<I", data, offset + 4)[0] != 0:
                raise DicomError("unexpected item delimiter")
            return offset + 8, "item_end"
        if tag in (ITEM, SEQUENCE_DELIMITER):
            raise DicomError(f"unexpected delimiter tag {tag} at {offset}")
        tag, vr, length, value_offset = _element_header(data, offset)
        if previous is not None and tag <= previous:
            raise DicomError(f"tags out of order at {offset}: {tag} after {previous}")
        previous = tag
        if top is not None and tag == PIXEL_DATA:
            top["__pixel__"] = (offset, vr, length, value_offset)
            return offset, "pixel"
        if vr == b"SQ":
            offset = _walk_items(data, value_offset, length, depth + 1)
            continue
        if length == UNDEFINED:
            raise DicomError(f"undefined length on non-sequence element {tag}")
        if value_offset + length > end:
            raise DicomError(f"element {tag} extends past its container")
        if top is not None:
            top[tag] = (vr, data[value_offset:value_offset + length])
        offset = value_offset + length
    if offset != end:
        raise DicomError("element overran container end")
    return offset, "end"


def parse_header(data: bytes) -> dict:
    """Walk the top-level dataset of a DICOM Part 10 stream up to Pixel Data.

    `data` may be a prefix of the file as long as it contains the Pixel Data
    element header. Sequences of defined or undefined length are skipped.
    """
    if len(data) < 132 or data[128:132] != b"DICM":
        raise DicomError("DICOM preamble missing")
    top: dict = {}
    _, reason = _walk(data, 132, len(data), 0, top)
    if reason != "pixel":
        raise DicomError("Pixel Data element not found")
    return top


def text(top: dict, tag: tuple[int, int]) -> str | None:
    if tag not in top:
        return None
    raw = top[tag][1]
    if not all(byte in (0, 9, 10, 13, 27) or 32 <= byte <= 126 for byte in raw):
        raise DicomError(f"non-ASCII text value for {tag}")
    return raw.decode("ascii").rstrip("\0 ").lstrip(" ")


def us(top: dict, tag: tuple[int, int]) -> int | None:
    if tag not in top:
        return None
    vr, raw = top[tag]
    if vr != b"US" or len(raw) != 2:
        raise DicomError(f"tag {tag} is not a single US value")
    return struct.unpack("<H", raw)[0]


def ds(top: dict, tag: tuple[int, int]) -> float | None:
    value = text(top, tag)
    return None if value is None else float(value)


# --------------------------------------------------------------------------
# Pinned-schema validation
# --------------------------------------------------------------------------

def read_pins(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or list(rows[0].keys()) != PIN_COLUMNS:
        raise DicomError("pinned_series.tsv columns changed")
    if len(rows) != EXPECTED_IMAGES:
        raise DicomError(f"expected {EXPECTED_IMAGES} pinned series, found {len(rows)}")
    if [int(row["ordinal"]) for row in rows] != list(range(1, EXPECTED_IMAGES + 1)):
        raise DicomError("pinned ordinals are not 1..N")
    for key in ("patient_id", "series_instance_uid", "sop_instance_uid"):
        if len({row[key] for row in rows}) != len(rows):
            raise DicomError(f"pinned {key} values are not unique")
    return rows


def validate_header(top: dict, pin: dict[str, str] | None, file_size: int) -> dict:
    """Assert the pinned acquisition regime; return the facts used downstream."""
    def require(tag: tuple[int, int], expected: str) -> None:
        actual = text(top, tag)
        if actual != expected:
            raise DicomError(f"tag ({tag[0]:04X},{tag[1]:04X}) = {actual!r}, expected {expected!r}")

    require((0x0002, 0x0010), TRANSFER_SYNTAX)
    require((0x0002, 0x0002), CR_SOP_CLASS)
    require((0x0008, 0x0016), CR_SOP_CLASS)
    require((0x0008, 0x0008), "DERIVED\\PRIMARY")
    require((0x0008, 0x0060), "CR")
    require((0x0008, 0x0070), "CARESTREAM HEALTH")
    require((0x0008, 0x1090), "DRX-REVOLUTION")
    require((0x0008, 0x103E), "AP")
    require((0x0018, 0x5101), "AP")
    require((0x0013, 0x1010), "COVID-19-NY-SBU")
    require((0x0028, 0x0004), "MONOCHROME2")
    require((0x0028, 0x0301), "NO")
    require((0x0018, 0x1164), "0.139\\0.139")
    body_part = text(top, (0x0018, 0x0015)) or ""
    if "CHEST" not in body_part:
        raise DicomError(f"BodyPartExamined {body_part!r} is not chest")
    lossy = text(top, (0x0028, 0x2110))
    if lossy not in (None, "00"):
        raise DicomError(f"LossyImageCompression {lossy!r}")
    presentation_lut = text(top, (0x2050, 0x0020))
    if presentation_lut not in (None, "IDENTITY"):
        raise DicomError(f"PresentationLUTShape {presentation_lut!r}")
    frames = text(top, (0x0028, 0x0008))
    if frames not in (None, "1"):
        raise DicomError(f"NumberOfFrames {frames!r}")
    schema = tuple(us(top, (0x0028, element)) for element in (0x0002, 0x0010, 0x0011, 0x0100, 0x0101, 0x0102, 0x0103))
    if schema != (1, ROWS, COLUMNS, 16, BITS_STORED, BITS_STORED - 1, 0):
        raise DicomError(f"pixel schema changed: {schema}")
    if ds(top, (0x0028, 0x1052)) != 0.0 or ds(top, (0x0028, 0x1053)) != 1.0:
        raise DicomError("rescale is not identity (intercept 0, slope 1)")
    software = text(top, (0x0018, 0x1020))
    if software not in SOFTWARE_VERSIONS:
        raise DicomError(f"unexpected SoftwareVersions {software!r}")
    sop = text(top, (0x0008, 0x0018))
    if text(top, (0x0002, 0x0003)) != sop:
        raise DicomError("MediaStorageSOPInstanceUID differs from SOPInstanceUID")
    tag_offset, vr, length, value_offset = top["__pixel__"]
    if vr != b"OW" or length != PIXEL_BYTES:
        raise DicomError(f"Pixel Data is not native OW of {PIXEL_BYTES} bytes: {vr!r} {length}")
    if value_offset + length != file_size:
        raise DicomError("Pixel Data is not the final element of the file")
    facts = {
        "patient_id": text(top, (0x0010, 0x0020)),
        "study_instance_uid": text(top, (0x0020, 0x000D)),
        "series_instance_uid": text(top, (0x0020, 0x000E)),
        "sop_instance_uid": sop,
        "software_versions": software,
        "pixel_value_offset": value_offset,
    }
    if pin is not None:
        for key in ("patient_id", "study_instance_uid", "series_instance_uid", "sop_instance_uid", "software_versions"):
            if facts[key] != pin[key]:
                raise DicomError(f"{key} {facts[key]!r} differs from pin {pin[key]!r}")
        if file_size != int(pin["file_size"]) or value_offset != int(pin["header_bytes"]):
            raise DicomError("file size or header length differs from pin")
    return facts


def header_digest(data: bytes, header_bytes: int) -> str:
    return hashlib.sha256(data[:header_bytes]).hexdigest()


def validate_file(path: Path, pin: dict[str, str]) -> tuple[bytes, dict]:
    data = path.read_bytes()
    if len(data) != int(pin["file_size"]):
        raise DicomError(f"{path.name}: size {len(data)} != pinned {pin['file_size']}")
    top = parse_header(data)
    facts = validate_header(top, pin, len(data))
    if header_digest(data, facts["pixel_value_offset"]) != pin["header_sha256"]:
        raise DicomError(f"{path.name}: header SHA-256 differs from pin")
    return data, facts


# --------------------------------------------------------------------------
# Pixel statistics
# --------------------------------------------------------------------------

def pixel_stats(payload: bytes) -> dict:
    values = array("H")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != VALUES_PER_IMAGE:
        raise DicomError("pixel count changed")
    maximum = max(values)
    minimum = min(values)
    if maximum > MAX_STORED_VALUE:
        raise DicomError(f"pixel value {maximum} exceeds 12-bit BitsStored range")
    distinct = len(set(values))
    zero_count = values.count(0)
    row_bytes = COLUMNS * 2
    distinct_rows = len({payload[offset:offset + row_bytes] for offset in range(0, len(payload), row_bytes)})
    if distinct < 256 or minimum == maximum or distinct_rows < ROWS // 4:
        raise DicomError("degenerate radiograph pixel plane")
    if zero_count > VALUES_PER_IMAGE // 2:
        raise DicomError("more than half of the radiograph is zero border")
    return {
        "distinct_rows": distinct_rows,
        "distinct_values": distinct,
        "maximum": maximum,
        "minimum": minimum,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "value_count": len(values),
        "value_sum": sum(values),
        "zero_count": zero_count,
    }


# --------------------------------------------------------------------------
# Build / verify
# --------------------------------------------------------------------------

def dicom_name(pin: dict[str, str]) -> str:
    return f"{int(pin['ordinal']):02d}_{pin['series_instance_uid']}.dcm"


def sample_name(pin: dict[str, str]) -> str:
    return f"chest_cr_{int(pin['ordinal']):02d}.bin"


def load_inventory(download_dir: Path, pins: list[dict[str, str]]) -> dict[str, dict]:
    inventory = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    if inventory.get("dataset_id") != DATASET_ID:
        raise DicomError("download inventory identity changed")
    records = {record["file"]: record for record in inventory.get("records", [])}
    if set(records) != {dicom_name(pin) for pin in pins}:
        raise DicomError("download inventory differs from pinned series")
    return records


def index_row(pin: dict[str, str], path: Path, data_root: Path, stats: dict, source: Path) -> dict:
    return {
        "bit_width": 16,
        "dataset_id": DATASET_ID,
        "distinct_values": stats["distinct_values"],
        "element_size_bytes": 2,
        "endianness": "little",
        "maximum": stats["maximum"],
        "minimum": stats["minimum"],
        "natural_record_kind": "complete_dicom_chest_radiograph_pixel_plane",
        "numeric_kind": "uint",
        "role": "primary",
        "sample_axes": ["image_row", "image_column"],
        "sample_format": "raw homogeneous little-endian unsigned-int16 chest radiograph plane (12 bits stored)",
        "sample_geometry": "fixed_2544x3056_chest_radiograph",
        "sample_path": path.relative_to(data_root).as_posix(),
        "sample_rank": 2,
        "sample_shape": [ROWS, COLUMNS],
        "sample_size_bytes": PIXEL_BYTES,
        "series_id": SERIES_ID,
        "sha256": stats["sha256"],
        "source_file": source.relative_to(data_root).as_posix(),
        "source_series_instance_uid": pin["series_instance_uid"],
        "source_software_versions": pin["software_versions"],
        "source_variable": "Pixel Data (7FE0,0010)",
        "value_count": stats["value_count"],
        "zero_count": stats["zero_count"],
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def summarize(rows: list[dict], details: list[dict]) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "distinct_patients": len({detail["patient_id"] for detail in details}),
        "global_maximum": max(row["maximum"] for row in rows),
        "global_minimum": min(row["minimum"] for row in rows),
        "images": len(rows),
        "primary_bytes": sum(row["sample_size_bytes"] for row in rows),
        "primary_values": sum(row["value_count"] for row in rows),
        "records": details,
        "series_id": SERIES_ID,
        "software_versions": sorted({row["source_software_versions"] for row in rows}),
        "total_zero_count": sum(row["zero_count"] for row in rows),
        "values_per_image": VALUES_PER_IMAGE,
    }


def build(args: argparse.Namespace) -> None:
    pins = read_pins(args.pins)
    inventory = load_inventory(args.download_dir, pins)
    samples_dir: Path = args.samples_dir
    samples_dir.mkdir(parents=True, exist_ok=True)
    for stale in samples_dir.glob("*"):
        if stale.is_file():
            stale.unlink()
    rows, details, hashes = [], [], set()
    for pin in pins:
        source = args.download_dir / "images" / dicom_name(pin)
        data, facts = validate_file(source, pin)
        if hashlib.sha256(data).hexdigest() != inventory[source.name]["sha256"]:
            raise DicomError(f"{source.name}: SHA-256 differs from download inventory")
        offset = facts["pixel_value_offset"]
        payload = data[offset:offset + PIXEL_BYTES]
        stats = pixel_stats(payload)
        if stats["sha256"] in hashes:
            raise DicomError("duplicate radiograph pixel plane")
        hashes.add(stats["sha256"])
        output = samples_dir / sample_name(pin)
        temporary = output.with_suffix(".tmp")
        temporary.write_bytes(payload)
        temporary.replace(output)
        rows.append(index_row(pin, output, args.data_root, stats, source))
        details.append({
            "dicom_bytes": len(data),
            "dicom_sha256": inventory[source.name]["sha256"],
            "ordinal": int(pin["ordinal"]),
            "patient_id": facts["patient_id"],
            "pixel_value_offset": offset,
            "value_sum": stats["value_sum"],
            "distinct_rows": stats["distinct_rows"],
        })
        print(f"built {output.name} min={stats['minimum']} max={stats['maximum']} distinct={stats['distinct_values']} zeros={stats['zero_count']}")
    write_jsonl(args.index, rows)
    summary = summarize(rows, details)
    write_json(args.stats, summary)
    print(f"mode=build images={summary['images']} primary_values={summary['primary_values']} primary_bytes={summary['primary_bytes']}")


def verify(args: argparse.Namespace) -> None:
    pins = read_pins(args.pins)
    inventory = load_inventory(args.download_dir, pins)
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [entry for entry in manifest["series"] if entry["id"] == SERIES_ID]
    if len(series) != 1:
        raise DicomError("manifest series missing")
    expected_names = {sample_name(pin) for pin in pins}
    present = {path.name for path in args.samples_dir.iterdir()} if args.samples_dir.is_dir() else set()
    if present != expected_names:
        raise DicomError(f"sample directory inventory differs: extra={sorted(present - expected_names)} missing={sorted(expected_names - present)}")
    rows, details, hashes, patients = [], [], set(), set()
    for pin in pins:
        source = args.download_dir / "images" / dicom_name(pin)
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != inventory[source.name]["sha256"]:
            raise DicomError(f"{source.name}: SHA-256 differs from download inventory")
        # Independent locator: native Pixel Data must be the final element, so
        # its value starts exactly PIXEL_BYTES before end of file and is
        # preceded by an explicit-VR OW element header with that length.
        offset = len(data) - PIXEL_BYTES
        expected_element = struct.pack("<HH2sHI", 0x7FE0, 0x0010, b"OW", 0, PIXEL_BYTES)
        if data[offset - 12:offset] != expected_element:
            raise DicomError(f"{source.name}: tail locator does not find the native Pixel Data element")
        top = parse_header(data)
        facts = validate_header(top, pin, len(data))
        if facts["pixel_value_offset"] != offset:
            raise DicomError(f"{source.name}: walker and tail locator disagree")
        if facts["patient_id"] in patients:
            raise DicomError("duplicate patient among pinned images")
        patients.add(facts["patient_id"])
        payload = data[offset:]
        sample = args.samples_dir / sample_name(pin)
        if sample.read_bytes() != payload:
            raise DicomError(f"{sample.name}: differs from DICOM Pixel Data")
        stats = pixel_stats(payload)
        if stats["sha256"] in hashes:
            raise DicomError("duplicate radiograph pixel plane")
        hashes.add(stats["sha256"])
        rows.append(index_row(pin, sample, args.data_root, stats, source))
        details.append({
            "dicom_bytes": len(data),
            "dicom_sha256": inventory[source.name]["sha256"],
            "ordinal": int(pin["ordinal"]),
            "patient_id": facts["patient_id"],
            "pixel_value_offset": offset,
            "value_sum": stats["value_sum"],
            "distinct_rows": stats["distinct_rows"],
        })
    with args.index.open(encoding="utf-8") as handle:
        indexed = [json.loads(line) for line in handle if line.strip()]
    if indexed != rows:
        raise DicomError("sample index differs from independent decode")
    summary = summarize(rows, details)
    if json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise DicomError("ingest stats differ from independent decode")
    if series[0]["sample_count"] != len(rows) or series[0]["total_size_bytes"] != summary["primary_bytes"]:
        raise DicomError("manifest sample_count/total_size_bytes differ from realized output")
    if summary["distinct_patients"] != EXPECTED_IMAGES:
        raise DicomError("images are not from distinct patients")
    print(f"mode=verify images={summary['images']} patients={summary['distinct_patients']} primary_values={summary['primary_values']} primary_bytes={summary['primary_bytes']} range={summary['global_minimum']}..{summary['global_maximum']}")


def validate_cli(args: argparse.Namespace) -> None:
    pins = {row["series_instance_uid"]: row for row in read_pins(args.pins)}
    pin = pins.get(args.series)
    if pin is None:
        raise DicomError("series is not pinned")
    data, facts = validate_file(args.file, pin)
    pixel_stats(data[facts["pixel_value_offset"]:])
    print(f"dicom_validation=ok ordinal={pin['ordinal']} bytes={len(data)} sha256={hashlib.sha256(data).hexdigest()}")


# --------------------------------------------------------------------------
# Synthetic self-test
# --------------------------------------------------------------------------

def _el(group: int, element: int, vr: bytes, value: bytes, undefined: bool = False) -> bytes:
    if vr in LONG_VR:
        return struct.pack("<HH2sHI", group, element, vr, 0, UNDEFINED if undefined else len(value)) + value
    return struct.pack("<HH2sH", group, element, vr, len(value)) + value


def _txt(value: str) -> bytes:
    raw = value.encode("ascii")
    return raw + (b" " if len(raw) % 2 else b"")


def _uid(value: str) -> bytes:
    raw = value.encode("ascii")
    return raw + (b"\0" if len(raw) % 2 else b"")


def _synthetic(rows: int, columns: int, undefined_sequences: bool, *, pixel_rows: int | None = None) -> tuple[bytes, bytes]:
    pixel_rows = rows if pixel_rows is None else pixel_rows
    values = array("H", [((r * 37 + c * 11) % 4096) for r in range(pixel_rows) for c in range(columns)])
    pixels = values.tobytes()
    item_body = _el(0x0008, 0x0100, b"SH", _txt("CXR14")) + _el(0x0008, 0x0104, b"LO", _txt("CHEST AP PORT"))
    nested = _el(0x0008, 0x1150, b"UI", _uid(CR_SOP_CLASS))
    if undefined_sequences:
        inner_seq = _el(0x0040, 0xA730, b"SQ", struct.pack("<HHI", 0xFFFE, 0xE000, UNDEFINED) + nested + struct.pack("<HHI", 0xFFFE, 0xE00D, 0) + struct.pack("<HHI", 0xFFFE, 0xE0DD, 0), undefined=True)
        item = struct.pack("<HHI", 0xFFFE, 0xE000, UNDEFINED) + item_body + inner_seq + struct.pack("<HHI", 0xFFFE, 0xE00D, 0)
        sequence = _el(0x0008, 0x1032, b"SQ", item + struct.pack("<HHI", 0xFFFE, 0xE0DD, 0), undefined=True)
    else:
        inner_seq = _el(0x0040, 0xA730, b"SQ", struct.pack("<HHI", 0xFFFE, 0xE000, len(nested)) + nested)
        body = item_body + inner_seq
        item = struct.pack("<HHI", 0xFFFE, 0xE000, len(body)) + body
        sequence = _el(0x0008, 0x1032, b"SQ", item)
    meta_body = (
        _el(0x0002, 0x0002, b"UI", _uid(CR_SOP_CLASS))
        + _el(0x0002, 0x0003, b"UI", _uid("1.2.3.4"))
        + _el(0x0002, 0x0010, b"UI", _uid(TRANSFER_SYNTAX))
    )
    meta = _el(0x0002, 0x0000, b"UL", struct.pack("<I", len(meta_body))) + meta_body
    dataset = (
        _el(0x0008, 0x0008, b"CS", _txt("DERIVED\\PRIMARY"))
        + _el(0x0008, 0x0016, b"UI", _uid(CR_SOP_CLASS))
        + _el(0x0008, 0x0018, b"UI", _uid("1.2.3.4"))
        + _el(0x0008, 0x0060, b"CS", _txt("CR"))
        + _el(0x0008, 0x0070, b"LO", _txt("CARESTREAM HEALTH"))
        + sequence
        + _el(0x0008, 0x103E, b"LO", _txt("AP"))
        + _el(0x0008, 0x1090, b"LO", _txt("DRX-REVOLUTION"))
        + _el(0x0009, 0x0010, b"LO", _txt("GEIIS"))
        + _el(0x0010, 0x0020, b"LO", _txt("P1"))
        + _el(0x0013, 0x1010, b"LO", _txt("COVID-19-NY-SBU"))
        + _el(0x0018, 0x0015, b"CS", _txt("PORT CHEST"))
        + _el(0x0018, 0x1020, b"LO", _txt("5.7.712.8007"))
        + _el(0x0018, 0x1164, b"DS", _txt("0.139\\0.139"))
        + _el(0x0018, 0x5101, b"CS", _txt("AP"))
        + _el(0x0020, 0x000D, b"UI", _uid("1.2.3"))
        + _el(0x0020, 0x000E, b"UI", _uid("1.2.3.9"))
        + _el(0x0028, 0x0002, b"US", struct.pack("<H", 1))
        + _el(0x0028, 0x0004, b"CS", _txt("MONOCHROME2"))
        + _el(0x0028, 0x0010, b"US", struct.pack("<H", rows))
        + _el(0x0028, 0x0011, b"US", struct.pack("<H", columns))
        + _el(0x0028, 0x0100, b"US", struct.pack("<H", 16))
        + _el(0x0028, 0x0101, b"US", struct.pack("<H", 12))
        + _el(0x0028, 0x0102, b"US", struct.pack("<H", 11))
        + _el(0x0028, 0x0103, b"US", struct.pack("<H", 0))
        + _el(0x0028, 0x0301, b"CS", _txt("NO"))
        + _el(0x0028, 0x1052, b"DS", _txt("0"))
        + _el(0x0028, 0x1053, b"DS", _txt("1"))
        + _el(0x0028, 0x2110, b"CS", _txt("00"))
        + _el(0x2050, 0x0020, b"CS", _txt("IDENTITY"))
        + _el(0x7FD1, 0x0010, b"LO", _txt("GEIIS"))
        + _el(0x7FD1, 0x1040, b"UL", struct.pack("<6I", 80, 159, 318, 636, 1272, 2544))
        + _el(0x7FE0, 0x0010, b"OW", pixels)
    )
    return b"\0" * 128 + b"DICM" + meta + dataset, pixels


def selftest(_: argparse.Namespace) -> None:
    global ROWS, COLUMNS, VALUES_PER_IMAGE, PIXEL_BYTES
    saved = (ROWS, COLUMNS, VALUES_PER_IMAGE, PIXEL_BYTES)
    try:
        ROWS, COLUMNS = 64, 48
        VALUES_PER_IMAGE = ROWS * COLUMNS
        PIXEL_BYTES = VALUES_PER_IMAGE * 2
        for undefined in (False, True):
            data, pixels = _synthetic(ROWS, COLUMNS, undefined)
            top = parse_header(data)
            facts = validate_header(top, None, len(data))
            assert facts["pixel_value_offset"] == len(data) - PIXEL_BYTES
            assert data[facts["pixel_value_offset"]:] == pixels
            assert facts["patient_id"] == "P1" and facts["series_instance_uid"] == "1.2.3.9"
            assert (0x0008, 0x0100) not in top, "nested item element leaked to top level"
            assert text(top, (0x0008, 0x103E)) == "AP"
            stats = pixel_stats(pixels)
            assert stats["maximum"] <= 4095 and stats["distinct_values"] >= 256
            # A header prefix (no pixel bytes) must still parse.
            prefix_top = parse_header(data[:facts["pixel_value_offset"]])
            assert prefix_top["__pixel__"][3] == facts["pixel_value_offset"]
            # Truncated mid-header must fail.
            try:
                parse_header(data[:400])
            except DicomError:
                pass
            else:
                raise AssertionError("truncated header accepted")
        # Wrong geometry must be rejected.
        data, _ = _synthetic(ROWS + 1, COLUMNS, True)
        try:
            validate_header(parse_header(data), None, len(data))
        except DicomError:
            pass
        else:
            raise AssertionError("wrong Rows accepted")
        # Pixel data not ending the file must be rejected.
        data, _ = _synthetic(ROWS, COLUMNS, False)
        try:
            validate_header(parse_header(data + b"\0\0"), None, len(data) + 2)
        except DicomError:
            pass
        else:
            raise AssertionError("trailing bytes accepted")
        # Values above 12 bits must be rejected.
        bad = array("H", [4096] * 10 + [i % 4096 for i in range(VALUES_PER_IMAGE - 10)]).tobytes()
        try:
            pixel_stats(bad)
        except DicomError:
            pass
        else:
            raise AssertionError("13-bit value accepted")
        # Constant plane must be rejected.
        try:
            pixel_stats(array("H", [7] * VALUES_PER_IMAGE).tobytes())
        except DicomError:
            pass
        else:
            raise AssertionError("constant plane accepted")
    finally:
        ROWS, COLUMNS, VALUES_PER_IMAGE, PIXEL_BYTES = saved
    print("selftest=ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("build", "verify"):
        p = sub.add_parser(mode)
        p.add_argument("--pins", type=Path, required=True)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--samples-dir", type=Path, required=True)
        p.add_argument("--index", type=Path, required=True)
        p.add_argument("--stats", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        if mode == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    p = sub.add_parser("validate")
    p.add_argument("--pins", type=Path, required=True)
    p.add_argument("--series", required=True)
    p.add_argument("--file", type=Path, required=True)
    sub.add_parser("selftest")
    args = parser.parse_args()
    try:
        {"build": build, "verify": verify, "validate": validate_cli, "selftest": selftest}[args.mode](args)
    except DicomError as exc:
        raise SystemExit(f"FATAL: {exc}")


if __name__ == "__main__":
    main()
