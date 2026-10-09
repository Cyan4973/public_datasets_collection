#!/usr/bin/env python3
"""Pure-stdlib DICOM header walker and voxel extractor for the pinned ReMIND
intraoperative 3D ultrasound volumes (US_pre_dura sweeps).

Each pinned object is a PixelMed NRRDToDicom Multi-frame Grayscale Byte
Secondary Capture image (one file per series) in Explicit VR Little Endian
with native 8-bit OB Pixel Data as its final element.

Subcommands:
  validate  check one downloaded DICOM file against its pinned row (download.sh)
  build     emit one raw uint8 voxel volume per pinned series
  verify    independently re-derive every sample, index row and statistic
  selftest  exercise the walker and checks on synthetic DICOM streams
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys
import tomllib

DATASET_ID = "tcia_remind_intraop_brain_ultrasound_u8"
SERIES_ID = "remind_us_pre_dura_volume_u8"
TRANSFER_SYNTAX = "1.2.840.10008.1.2.1"
SOP_CLASS = "1.2.840.10008.5.1.4.1.1.7.2"  # Multi-frame Grayscale Byte SC Image Storage
SERIES_DESCRIPTION = "US_pre_dura"
EXPECTED_VOLUMES = 14
NATURAL_RECORD_KIND = "complete_dicom_3d_ultrasound_sweep_volume"
SAMPLE_FORMAT = "raw homogeneous unsigned-int8 3D B-mode ultrasound volume (frame-major, then row, then column)"
SAMPLE_GEOMETRY = "variable_frames_x_rows_x_columns_ultrasound_volume"
# Degeneracy limits (verify.sh applies the same ones).
MIN_DISTINCT_VALUES = 64
MAX_ZERO_FRACTION = 0.90
PIN_COLUMNS = [
    "ordinal",
    "patient_id",
    "study_instance_uid",
    "series_instance_uid",
    "sop_instance_uid",
    "file_size",
    "header_bytes",
    "header_sha256",
    "frames",
    "rows",
    "columns",
    "pixel_spacing_mm",
    "spacing_between_slices_mm",
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


def _walk_items(data: bytes, value_offset: int, length: int, depth: int, collect: dict | None) -> int:
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
            position, reason = _walk(data, position, len(data), depth, None, collect)
            if reason != "item_end":
                raise DicomError("undefined-length item without delimiter")
        else:
            item_end = position + item_length
            if item_end > len(data):
                raise DicomError("item extends past available data")
            stop, reason = _walk(data, position, item_end, depth, None, collect)
            if reason != "end" or stop != item_end:
                raise DicomError("defined-length item does not end at its boundary")
            position = item_end


# Nested tags whose first occurrence is collected (documentation only).
NESTED_COLLECT = {(0x0028, 0x0030), (0x0018, 0x0088), (0x0018, 0x0050)}


def _walk(
    data: bytes, offset: int, end: int, depth: int, top: dict | None, collect: dict | None
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
            offset = _walk_items(data, value_offset, length, depth + 1, collect)
            continue
        if length == UNDEFINED:
            raise DicomError(f"undefined length on non-sequence element {tag}")
        if value_offset + length > end:
            raise DicomError(f"element {tag} extends past its container")
        if top is not None:
            top[tag] = (vr, data[value_offset:value_offset + length])
        elif collect is not None and tag in NESTED_COLLECT and tag not in collect:
            collect[tag] = (vr, data[value_offset:value_offset + length])
        offset = value_offset + length
    if offset != end:
        raise DicomError("element overran container end")
    return offset, "end"


def parse_header(data: bytes) -> dict:
    """Walk the top-level dataset of a DICOM Part 10 stream up to Pixel Data.

    `data` may be a prefix of the file as long as it contains the Pixel Data
    element header. Sequences are skipped; the first nested Pixel Spacing,
    Spacing Between Slices and Slice Thickness values are kept under
    "__nested__" for documentation.
    """
    if len(data) < 132 or data[128:132] != b"DICM":
        raise DicomError("DICOM preamble missing")
    top: dict = {}
    nested: dict = {}
    _, reason = _walk(data, 132, len(data), 0, top, nested)
    if reason != "pixel":
        raise DicomError("Pixel Data element not found")
    top["__nested__"] = nested
    return top


def _ascii(raw: bytes, tag: tuple[int, int]) -> str:
    if not all(byte in (0, 9, 10, 13, 27) or 32 <= byte <= 126 for byte in raw):
        raise DicomError(f"non-ASCII text value for {tag}")
    return raw.decode("ascii").rstrip("\0 ").lstrip(" ")


def text(top: dict, tag: tuple[int, int]) -> str | None:
    if tag not in top:
        return None
    return _ascii(top[tag][1], tag)


def nested_text(top: dict, tag: tuple[int, int]) -> str:
    nested = top.get("__nested__", {})
    return _ascii(nested[tag][1], tag) if tag in nested else ""


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
    if len(rows) != EXPECTED_VOLUMES:
        raise DicomError(f"expected {EXPECTED_VOLUMES} pinned series, found {len(rows)}")
    if [int(row["ordinal"]) for row in rows] != list(range(1, EXPECTED_VOLUMES + 1)):
        raise DicomError("pinned ordinals are not 1..N")
    for key in ("patient_id", "series_instance_uid", "sop_instance_uid"):
        if len({row[key] for row in rows}) != len(rows):
            raise DicomError(f"pinned {key} values are not unique")
    return rows


def pixel_element_length(values: int) -> int:
    """OB values are padded with one byte to even length."""
    return values + (values & 1)


def validate_header(top: dict, pin: dict[str, str] | None, file_size: int) -> dict:
    """Assert the pinned acquisition/conversion regime; return the facts used downstream."""
    def require(tag: tuple[int, int], expected: str) -> None:
        actual = text(top, tag)
        if actual != expected:
            raise DicomError(f"tag ({tag[0]:04X},{tag[1]:04X}) = {actual!r}, expected {expected!r}")

    require((0x0002, 0x0010), TRANSFER_SYNTAX)
    require((0x0002, 0x0002), SOP_CLASS)
    require((0x0008, 0x0016), SOP_CLASS)
    require((0x0008, 0x0008), "DERIVED\\PRIMARY\\VOLUME\\NONE")
    require((0x0008, 0x0060), "US")
    require((0x0008, 0x0070), "PixelMed")
    require((0x0008, 0x1090), "com.pixelmed.convert.NRRDToDicom")
    require((0x0008, 0x103E), SERIES_DESCRIPTION)
    require((0x0013, 0x1010), "ReMIND")
    require((0x0028, 0x0004), "MONOCHROME2")
    require((0x0028, 0x0301), "NO")
    require((0x0012, 0x0062), "YES")
    lossy = text(top, (0x0028, 0x2110))
    if lossy not in (None, "00"):
        raise DicomError(f"LossyImageCompression {lossy!r}")
    presentation_lut = text(top, (0x2050, 0x0020))
    if presentation_lut not in (None, "IDENTITY"):
        raise DicomError(f"PresentationLUTShape {presentation_lut!r}")
    frames_text = text(top, (0x0028, 0x0008))
    if frames_text is None or not frames_text.isdigit() or int(frames_text) < 2:
        raise DicomError(f"NumberOfFrames {frames_text!r} is not a multi-frame volume")
    frames = int(frames_text)
    spp, rows, columns, allocated, stored, high, representation = (
        us(top, (0x0028, element)) for element in (0x0002, 0x0010, 0x0011, 0x0100, 0x0101, 0x0102, 0x0103)
    )
    if (spp, allocated, stored, high, representation) != (1, 8, 8, 7, 0):
        raise DicomError(f"pixel schema changed: spp={spp} bits={allocated}/{stored}/{high} pixrep={representation}")
    if not rows or not columns or rows < 16 or columns < 16:
        raise DicomError(f"implausible matrix {rows}x{columns}")
    if ds(top, (0x0028, 0x1052)) not in (None, 0.0) or ds(top, (0x0028, 0x1053)) not in (None, 1.0):
        raise DicomError("rescale is not identity (intercept 0, slope 1)")
    sop = text(top, (0x0008, 0x0018))
    if text(top, (0x0002, 0x0003)) != sop:
        raise DicomError("MediaStorageSOPInstanceUID differs from SOPInstanceUID")
    values = frames * rows * columns
    tag_offset, vr, length, value_offset = top["__pixel__"]
    if vr != b"OB" or length != pixel_element_length(values):
        raise DicomError(f"Pixel Data is not native OB of {pixel_element_length(values)} bytes: {vr!r} {length}")
    if value_offset + length != file_size:
        raise DicomError("Pixel Data is not the final element of the file")
    facts = {
        "patient_id": text(top, (0x0010, 0x0020)),
        "study_instance_uid": text(top, (0x0020, 0x000D)),
        "series_instance_uid": text(top, (0x0020, 0x000E)),
        "sop_instance_uid": sop,
        "frames": frames,
        "rows": rows,
        "columns": columns,
        "values": values,
        "pixel_value_offset": value_offset,
        "pixel_spacing_mm": nested_text(top, (0x0028, 0x0030)),
        "spacing_between_slices_mm": nested_text(top, (0x0018, 0x0088)),
    }
    if pin is not None:
        for key in ("patient_id", "study_instance_uid", "series_instance_uid", "sop_instance_uid",
                    "pixel_spacing_mm", "spacing_between_slices_mm"):
            if facts[key] != pin[key]:
                raise DicomError(f"{key} {facts[key]!r} differs from pin {pin[key]!r}")
        for key in ("frames", "rows", "columns"):
            if facts[key] != int(pin[key]):
                raise DicomError(f"{key} {facts[key]} differs from pin {pin[key]}")
        if file_size != int(pin["file_size"]) or value_offset != int(pin["header_bytes"]):
            raise DicomError("file size or header length differs from pin")
    return facts


def header_digest(data: bytes, header_bytes: int) -> str:
    return hashlib.sha256(data[:header_bytes]).hexdigest()


def extract_payload(data: bytes, offset: int, values: int) -> bytes:
    """Return exactly frames*rows*columns voxel bytes, dropping the OB pad byte."""
    payload = data[offset:offset + values]
    pad = data[offset + values:]
    if len(payload) != values or pad not in (b"", b"\0"):
        raise DicomError(f"Pixel Data tail is not a single zero pad byte: {pad[:4]!r}")
    return payload


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
# Voxel statistics
# --------------------------------------------------------------------------

def voxel_stats(payload: bytes, frames: int, rows: int, columns: int) -> dict:
    values = frames * rows * columns
    if len(payload) != values:
        raise DicomError("voxel count changed")
    histogram = Counter(payload)
    present = sorted(histogram)
    zero_count = histogram.get(0, 0)
    mode_value, mode_count = max(histogram.items(), key=lambda item: (item[1], -item[0]))
    frame_bytes = rows * columns
    frame_hashes = set()
    zero_frames = 0
    for start in range(0, values, frame_bytes):
        frame = payload[start:start + frame_bytes]
        if frame.count(0) == frame_bytes:
            zero_frames += 1
        frame_hashes.add(hashlib.sha256(frame).digest())
    stats = {
        "all_zero_frames": zero_frames,
        "distinct_frames": len(frame_hashes),
        "distinct_values": len(present),
        "maximum": present[-1],
        "minimum": present[0],
        "mode_fraction": round(mode_count / values, 6),
        "mode_value": mode_value,
        "nonzero_mean": round(sum(v * c for v, c in histogram.items()) / max(1, values - zero_count), 4),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "value_count": values,
        "zero_count": zero_count,
        "zero_fraction": round(zero_count / values, 6),
    }
    if stats["minimum"] == stats["maximum"] or stats["distinct_values"] < MIN_DISTINCT_VALUES:
        raise DicomError(f"degenerate volume: {stats['distinct_values']} distinct values")
    if zero_count > MAX_ZERO_FRACTION * values:
        raise DicomError(f"volume is {zero_count / values:.3f} zero background (limit {MAX_ZERO_FRACTION})")
    if zero_frames * 2 > frames or len(frame_hashes) * 2 < frames:
        raise DicomError(f"degenerate frames: {zero_frames} all-zero, {len(frame_hashes)} distinct of {frames}")
    return stats


# --------------------------------------------------------------------------
# Build / verify
# --------------------------------------------------------------------------

def dicom_name(pin: dict[str, str]) -> str:
    return f"{int(pin['ordinal']):02d}_{pin['series_instance_uid']}.dcm"


def sample_name(pin: dict[str, str]) -> str:
    return f"us_pre_dura_{int(pin['ordinal']):02d}.bin"


def load_inventory(download_dir: Path, pins: list[dict[str, str]]) -> dict[str, dict]:
    inventory = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    if inventory.get("dataset_id") != DATASET_ID:
        raise DicomError("download inventory identity changed")
    records = {record["file"]: record for record in inventory.get("records", [])}
    if set(records) != {dicom_name(pin) for pin in pins}:
        raise DicomError("download inventory differs from pinned series")
    return records


def index_row(pin: dict[str, str], path: Path, data_root: Path, stats: dict, source: Path, facts: dict) -> dict:
    return {
        "all_zero_frames": stats["all_zero_frames"],
        "bit_width": 8,
        "dataset_id": DATASET_ID,
        "distinct_values": stats["distinct_values"],
        "element_size_bytes": 1,
        "endianness": "little",
        "maximum": stats["maximum"],
        "minimum": stats["minimum"],
        "mode_fraction": stats["mode_fraction"],
        "mode_value": stats["mode_value"],
        "natural_record_kind": NATURAL_RECORD_KIND,
        "numeric_kind": "uint",
        "role": "primary",
        "sample_axes": ["frame", "image_row", "image_column"],
        "sample_format": SAMPLE_FORMAT,
        "sample_geometry": SAMPLE_GEOMETRY,
        "sample_path": path.relative_to(data_root).as_posix(),
        "sample_rank": 3,
        "sample_shape": [facts["frames"], facts["rows"], facts["columns"]],
        "sample_size_bytes": stats["value_count"],
        "series_id": SERIES_ID,
        "sha256": stats["sha256"],
        "source_file": source.relative_to(data_root).as_posix(),
        "source_patient_id": pin["patient_id"],
        "source_pixel_spacing_mm": pin["pixel_spacing_mm"],
        "source_series_instance_uid": pin["series_instance_uid"],
        "source_spacing_between_slices_mm": pin["spacing_between_slices_mm"],
        "source_variable": "Pixel Data (7FE0,0010)",
        "value_count": stats["value_count"],
        "zero_count": stats["zero_count"],
        "zero_fraction": stats["zero_fraction"],
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
    values = sum(row["value_count"] for row in rows)
    zeros = sum(row["zero_count"] for row in rows)
    return {
        "dataset_id": DATASET_ID,
        "distinct_patients": len({detail["patient_id"] for detail in details}),
        "global_maximum": max(row["maximum"] for row in rows),
        "global_minimum": min(row["minimum"] for row in rows),
        "primary_bytes": sum(row["sample_size_bytes"] for row in rows),
        "primary_values": values,
        "records": details,
        "series_id": SERIES_ID,
        "total_zero_count": zeros,
        "total_zero_fraction": round(zeros / values, 6),
        "volumes": len(rows),
    }


def detail_row(pin: dict[str, str], data: bytes, inventory: dict, source: Path, facts: dict) -> dict:
    return {
        "dicom_bytes": len(data),
        "dicom_sha256": inventory[source.name]["sha256"],
        "ordinal": int(pin["ordinal"]),
        "patient_id": facts["patient_id"],
        "pixel_value_offset": facts["pixel_value_offset"],
        "shape": [facts["frames"], facts["rows"], facts["columns"]],
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
        payload = extract_payload(data, facts["pixel_value_offset"], facts["values"])
        stats = voxel_stats(payload, facts["frames"], facts["rows"], facts["columns"])
        if stats["sha256"] in hashes:
            raise DicomError("duplicate ultrasound volume")
        hashes.add(stats["sha256"])
        output = samples_dir / sample_name(pin)
        temporary = output.with_suffix(".tmp")
        temporary.write_bytes(payload)
        temporary.replace(output)
        rows.append(index_row(pin, output, args.data_root, stats, source, facts))
        details.append(detail_row(pin, data, inventory, source, facts))
        print(
            f"built {output.name} shape={facts['frames']}x{facts['rows']}x{facts['columns']} "
            f"min={stats['minimum']} max={stats['maximum']} distinct={stats['distinct_values']} "
            f"zero_fraction={stats['zero_fraction']} zero_frames={stats['all_zero_frames']}"
        )
    write_jsonl(args.index, rows)
    summary = summarize(rows, details)
    write_json(args.stats, summary)
    print(f"mode=build volumes={summary['volumes']} primary_values={summary['primary_values']} "
          f"primary_bytes={summary['primary_bytes']} zero_fraction={summary['total_zero_fraction']}")


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
        # Independent locator: native OB Pixel Data is the final element, so
        # from the pinned geometry its value starts exactly element-length
        # bytes before end of file, preceded by an explicit-VR OB header.
        values = int(pin["frames"]) * int(pin["rows"]) * int(pin["columns"])
        length = pixel_element_length(values)
        offset = len(data) - length
        expected_element = struct.pack("<HH2sHI", 0x7FE0, 0x0010, b"OB", 0, length)
        if data[offset - 12:offset] != expected_element:
            raise DicomError(f"{source.name}: tail locator does not find the native Pixel Data element")
        top = parse_header(data)
        facts = validate_header(top, pin, len(data))
        if facts["pixel_value_offset"] != offset or facts["values"] != values:
            raise DicomError(f"{source.name}: walker and tail locator disagree")
        if header_digest(data, offset) != pin["header_sha256"]:
            raise DicomError(f"{source.name}: header SHA-256 differs from pin")
        if facts["patient_id"] in patients:
            raise DicomError("duplicate patient among pinned volumes")
        patients.add(facts["patient_id"])
        payload = data[offset:offset + values]
        if length != values and data[offset + values:] != b"\0":
            raise DicomError(f"{source.name}: OB pad byte is not zero")
        sample = args.samples_dir / sample_name(pin)
        if sample.read_bytes() != payload:
            raise DicomError(f"{sample.name}: differs from DICOM Pixel Data")
        stats = voxel_stats(payload, facts["frames"], facts["rows"], facts["columns"])
        if stats["sha256"] in hashes:
            raise DicomError("duplicate ultrasound volume")
        hashes.add(stats["sha256"])
        rows.append(index_row(pin, sample, args.data_root, stats, source, facts))
        details.append(detail_row(pin, data, inventory, source, facts))
    with args.index.open(encoding="utf-8") as handle:
        indexed = [json.loads(line) for line in handle if line.strip()]
    if indexed != rows:
        raise DicomError("sample index differs from independent decode")
    summary = summarize(rows, details)
    if json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise DicomError("ingest stats differ from independent decode")
    if series[0]["sample_count"] != len(rows) or series[0]["total_size_bytes"] != summary["primary_bytes"]:
        raise DicomError("manifest sample_count/total_size_bytes differ from realized output")
    if summary["primary_bytes"] > 1_000_000_000:
        raise DicomError("primary output exceeds the 1,000,000,000-byte cap")
    if summary["distinct_patients"] != EXPECTED_VOLUMES:
        raise DicomError("volumes are not from distinct patients")
    print(f"mode=verify volumes={summary['volumes']} patients={summary['distinct_patients']} "
          f"primary_values={summary['primary_values']} primary_bytes={summary['primary_bytes']} "
          f"range={summary['global_minimum']}..{summary['global_maximum']} zero_fraction={summary['total_zero_fraction']}")


def validate_cli(args: argparse.Namespace) -> None:
    pins = {row["series_instance_uid"]: row for row in read_pins(args.pins)}
    pin = pins.get(args.series)
    if pin is None:
        raise DicomError("series is not pinned")
    data, facts = validate_file(args.file, pin)
    payload = extract_payload(data, facts["pixel_value_offset"], facts["values"])
    voxel_stats(payload, facts["frames"], facts["rows"], facts["columns"])
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


def _voxels(frames: int, rows: int, columns: int) -> bytes:
    out = bytearray()
    for f in range(frames):
        for r in range(rows):
            for c in range(columns):
                # A cone-like zero background plus speckle-ish texture.
                inside = abs(c - columns // 2) <= (r * columns) // (2 * rows)
                out.append(((f * 7 + r * 13 + c * 29 + (r * c) % 17) % 255 + 1) if inside else 0)
    return bytes(out)


def _synthetic(frames: int, rows: int, columns: int, undefined_sequences: bool, *, bits: int = 8) -> tuple[bytes, bytes]:
    voxels = _voxels(frames, rows, columns)
    pixel_value = voxels + (b"\0" if len(voxels) % 2 else b"")
    spacing = _el(0x0028, 0x0030, b"DS", _txt(".125\\.125"))
    measures = _el(0x0018, 0x0050, b"DS", _txt(".5")) + _el(0x0018, 0x0088, b"DS", _txt(".5")) + spacing
    if undefined_sequences:
        inner = _el(0x0028, 0x9110, b"SQ", struct.pack("<HHI", 0xFFFE, 0xE000, UNDEFINED) + measures
                    + struct.pack("<HHI", 0xFFFE, 0xE00D, 0) + struct.pack("<HHI", 0xFFFE, 0xE0DD, 0), undefined=True)
        shared = _el(0x5200, 0x9229, b"SQ", struct.pack("<HHI", 0xFFFE, 0xE000, UNDEFINED) + inner
                     + struct.pack("<HHI", 0xFFFE, 0xE00D, 0) + struct.pack("<HHI", 0xFFFE, 0xE0DD, 0), undefined=True)
    else:
        inner_seq = _el(0x0028, 0x9110, b"SQ", struct.pack("<HHI", 0xFFFE, 0xE000, len(measures)) + measures)
        shared = _el(0x5200, 0x9229, b"SQ", struct.pack("<HHI", 0xFFFE, 0xE000, len(inner_seq)) + inner_seq)
    position = _el(0x0020, 0x0032, b"DS", _txt("1\\2\\3"))
    plane = _el(0x0020, 0x9113, b"SQ", struct.pack("<HHI", 0xFFFE, 0xE000, len(position)) + position)
    per_frame = _el(0x5200, 0x9230, b"SQ", b"".join(
        struct.pack("<HHI", 0xFFFE, 0xE000, len(plane)) + plane for _ in range(frames)))
    meta_body = (
        _el(0x0002, 0x0002, b"UI", _uid(SOP_CLASS))
        + _el(0x0002, 0x0003, b"UI", _uid("1.2.3.4"))
        + _el(0x0002, 0x0010, b"UI", _uid(TRANSFER_SYNTAX))
    )
    meta = _el(0x0002, 0x0000, b"UL", struct.pack("<I", len(meta_body))) + meta_body
    dataset = (
        _el(0x0008, 0x0008, b"CS", _txt("DERIVED\\PRIMARY\\VOLUME\\NONE"))
        + _el(0x0008, 0x0016, b"UI", _uid(SOP_CLASS))
        + _el(0x0008, 0x0018, b"UI", _uid("1.2.3.4"))
        + _el(0x0008, 0x0060, b"CS", _txt("US"))
        + _el(0x0008, 0x0070, b"LO", _txt("PixelMed"))
        + _el(0x0008, 0x103E, b"LO", _txt(SERIES_DESCRIPTION))
        + _el(0x0008, 0x1090, b"LO", _txt("com.pixelmed.convert.NRRDToDicom"))
        + _el(0x0010, 0x0020, b"LO", _txt("ReMIND-999"))
        + _el(0x0012, 0x0062, b"CS", _txt("YES"))
        + _el(0x0013, 0x0010, b"LO", _txt("CTP"))
        + _el(0x0013, 0x1010, b"LO", _txt("ReMIND"))
        + _el(0x0020, 0x000D, b"UI", _uid("1.2.3"))
        + _el(0x0020, 0x000E, b"UI", _uid("1.2.3.9"))
        + _el(0x0028, 0x0002, b"US", struct.pack("<H", 1))
        + _el(0x0028, 0x0004, b"CS", _txt("MONOCHROME2"))
        + _el(0x0028, 0x0008, b"IS", _txt(str(frames)))
        + _el(0x0028, 0x0010, b"US", struct.pack("<H", rows))
        + _el(0x0028, 0x0011, b"US", struct.pack("<H", columns))
        + _el(0x0028, 0x0100, b"US", struct.pack("<H", bits))
        + _el(0x0028, 0x0101, b"US", struct.pack("<H", bits))
        + _el(0x0028, 0x0102, b"US", struct.pack("<H", bits - 1))
        + _el(0x0028, 0x0103, b"US", struct.pack("<H", 0))
        + _el(0x0028, 0x0301, b"CS", _txt("NO"))
        + _el(0x0028, 0x1052, b"DS", _txt("0.0"))
        + _el(0x0028, 0x1053, b"DS", _txt("1.0"))
        + _el(0x0028, 0x2110, b"CS", _txt("00"))
        + _el(0x2050, 0x0020, b"CS", _txt("IDENTITY"))
        + shared
        + per_frame
        + _el(0x7FE0, 0x0010, b"OB", pixel_value)
    )
    return b"\0" * 128 + b"DICM" + meta + dataset, voxels


def _expect_failure(label: str, fn) -> None:
    try:
        fn()
    except DicomError:
        return
    raise AssertionError(f"{label} accepted")


def selftest(_: argparse.Namespace) -> None:
    # Odd voxel count (5*31*33) exercises the OB pad byte; even (6*32*40) does not.
    for frames, rows, columns in ((5, 31, 33), (6, 32, 40)):
        values = frames * rows * columns
        for undefined in (False, True):
            data, voxels = _synthetic(frames, rows, columns, undefined)
            top = parse_header(data)
            facts = validate_header(top, None, len(data))
            assert facts["values"] == values and facts["frames"] == frames
            assert facts["pixel_value_offset"] == len(data) - pixel_element_length(values)
            payload = extract_payload(data, facts["pixel_value_offset"], values)
            assert payload == voxels and len(payload) == values
            assert facts["pixel_spacing_mm"] == ".125\\.125" and facts["spacing_between_slices_mm"] == ".5"
            assert facts["patient_id"] == "ReMIND-999" and facts["series_instance_uid"] == "1.2.3.9"
            assert (0x0020, 0x0032) not in top, "nested per-frame element leaked to top level"
            stats = voxel_stats(payload, frames, rows, columns)
            assert 0 < stats["zero_fraction"] < 0.9 and stats["minimum"] == 0
            prefix_top = parse_header(data[:facts["pixel_value_offset"]])
            assert prefix_top["__pixel__"][3] == facts["pixel_value_offset"]
            _expect_failure("truncated header", lambda: parse_header(data[:300]))
    data, _ = _synthetic(5, 31, 33, False)
    _expect_failure("trailing bytes", lambda: validate_header(parse_header(data + b"\0\0"), None, len(data) + 2))
    bad_pad = data[:-1] + b"\x07"
    facts = validate_header(parse_header(bad_pad), None, len(bad_pad))
    _expect_failure("nonzero pad byte", lambda: extract_payload(bad_pad, facts["pixel_value_offset"], facts["values"]))
    data16, _ = _synthetic(5, 31, 33, False, bits=16)
    _expect_failure("16-bit schema", lambda: validate_header(parse_header(data16), None, len(data16)))
    _expect_failure("constant volume", lambda: voxel_stats(bytes([9]) * (6 * 32 * 40), 6, 32, 40))
    mostly_zero = bytes(6 * 32 * 40 - 300) + bytes(range(1, 256)) + bytes(45)
    _expect_failure("mostly-zero volume", lambda: voxel_stats(mostly_zero, 6, 32, 40))
    one_frame = _voxels(1, 32, 40)
    _expect_failure("repeated frames", lambda: voxel_stats(one_frame * 6, 6, 32, 40))
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
