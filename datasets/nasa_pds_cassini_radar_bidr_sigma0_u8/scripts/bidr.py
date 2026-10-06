#!/usr/bin/env python3
"""Shared helpers for the Cassini RADAR BIBQH (8-bit dB sigma0) recipe.

Pure standard library. Parses PDS3 labels (attached or detached), holds the
pinned product-family constants, and validates one product's attached label
against the pinned plan row.
"""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

DATASET_ID = "nasa_pds_cassini_radar_bidr_sigma0_u8"
SERIES_ID = "cassini_radar_bidr_sigma0_db_u8"
BUCKET_URL = "https://asc-pds-cassini.s3.us-west-2.amazonaws.com/"

# Family constants every selected product must carry (verified on all 22).
DATA_SET_ID = "CO-SSA-RADAR-5-BIDR-V1.0"
TARGET_NAME = "TITAN"
SAMPLE_TYPE = "UNSIGNED_INTEGER"
SAMPLE_BITS = "8"
SCALING_FACTOR = "1.0000012E-01"
OFFSET = "-2.0100010E+01"
MISSING_CONSTANT = "0"
MAP_RESOLUTION = "128.0<PIX/DEG>"
MAP_PROJECTION_TYPE = "OBLIQUE CYLINDRICAL"
PRODUCER_INSTITUTION_NAME = "U.S.G.S. FLAGSTAFF"

PRODUCT_RE = re.compile(
    r"^BIBQH(?P<lat>\d\d[NS])(?P<lon>\d{3})_D(?P<datatake>\d{3})_T(?P<flyby>\d{3}|00A)"
    r"S(?P<segment>\d\d)_V(?P<version>\d\d)$"
)

# Pinned source plan identity (sources.tsv) and aggregates.
SOURCES_SHA256 = "b59c6fabe0d1941ac6bc85f65367f9aa713799700cb974438643f7c5b5895caf"
EXPECTED_PRODUCTS = 22
EXPECTED_ZIP_BYTES = 89_704_750
EXPECTED_IMG_BYTES = 343_599_232
EXPECTED_PIXEL_BYTES = 343_474_176

PLAN_COLUMNS = [
    "ordinal",
    "volume",
    "product_id",
    "flyby",
    "segment",
    "datatake",
    "zip_bytes",
    "zip_md5",
    "zip_member_crc32",
    "zip_member_compressed_bytes",
    "img_bytes",
    "img_md5",
    "record_bytes",
    "file_records",
    "label_records",
    "image_start_record",
    "lines",
    "line_samples",
    "image_checksum",
    "start_time",
    "stop_time",
]
INT_COLUMNS = {
    "ordinal",
    "zip_bytes",
    "zip_member_compressed_bytes",
    "img_bytes",
    "record_bytes",
    "file_records",
    "label_records",
    "image_start_record",
    "lines",
    "line_samples",
    "image_checksum",
}


def flyby_order(flyby: str) -> int:
    """T00A ('Ta', 2004-10-26) precedes T003; numeric otherwise."""
    return 0 if flyby == "00A" else int(flyby)


def zip_url(row: dict) -> str:
    return f"{BUCKET_URL}RADAR/{row['volume']}/DATA/BIDR/{row['product_id']}.ZIP"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_plan(path: Path, *, check_identity: bool = True) -> list[dict]:
    raw = path.read_bytes()
    if check_identity and hashlib.sha256(raw).hexdigest() != SOURCES_SHA256:
        raise SystemExit(f"pinned source plan identity changed: {path}")
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines(), delimiter="\t"))
    if not rows or list(rows[0].keys()) != PLAN_COLUMNS:
        raise SystemExit("source plan columns changed")
    out = []
    for row in rows:
        parsed = {key: (int(value) if key in INT_COLUMNS else value) for key, value in row.items()}
        if not PRODUCT_RE.match(parsed["product_id"]) or not re.fullmatch(r"CORADR_\d{4}", parsed["volume"]):
            raise SystemExit(f"unsafe product or volume name in plan: {parsed['product_id']}")
        if not re.fullmatch(r"[0-9a-f]{32}", parsed["zip_md5"]) or not re.fullmatch(r"[0-9a-f]{32}", parsed["img_md5"]):
            raise SystemExit(f"invalid pinned MD5 in plan: {parsed['product_id']}")
        if not re.fullmatch(r"[0-9a-f]{8}", parsed["zip_member_crc32"]):
            raise SystemExit(f"invalid pinned CRC32 in plan: {parsed['product_id']}")
        out.append(parsed)
    if [row["ordinal"] for row in out] != list(range(1, len(out) + 1)):
        raise SystemExit("source plan ordinals changed")
    if len({row["product_id"] for row in out}) != len(out):
        raise SystemExit("duplicate product in source plan")
    if len({row["product_id"][:-4] for row in out}) != len(out):
        raise SystemExit("duplicate product base (multiple versions) in source plan")
    if check_identity:
        if len(out) != EXPECTED_PRODUCTS:
            raise SystemExit("source plan product count changed")
        if sum(row["zip_bytes"] for row in out) != EXPECTED_ZIP_BYTES:
            raise SystemExit("source plan ZIP byte aggregate changed")
        if sum(row["img_bytes"] for row in out) != EXPECTED_IMG_BYTES:
            raise SystemExit("source plan IMG byte aggregate changed")
        if sum(row["lines"] * row["line_samples"] for row in out) != EXPECTED_PIXEL_BYTES:
            raise SystemExit("source plan pixel aggregate changed")
    return out


# ---------------------------------------------------------------- PDS3 labels

_ASSIGN_RE = re.compile(r"^\s*(\^?[A-Z0-9_:]+)\s*=\s*(.*)$")


def label_text_from_prefix(prefix: bytes) -> str:
    """Return the attached PDS3 label text (through the END line)."""
    match = re.search(rb"\r?\nEND\s*\r?\n", prefix)
    if not prefix.startswith(b"PDS_VERSION_ID") or match is None:
        raise ValueError("attached PDS3 label not found or not terminated by END")
    return prefix[: match.end()].decode("ascii")


def parse_pds3(text: str) -> dict[str, str]:
    """Flatten a PDS3 label into dotted OBJECT paths -> raw value strings.

    Handles OBJECT/END_OBJECT nesting, multi-line quoted strings, multi-line
    parenthesized sequences, and /* */ comments on their own lines. Values are
    returned with surrounding double quotes removed; whitespace inside quoted
    strings is collapsed to single spaces.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    stack: list[str] = []
    result: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("/*"):
            continue
        if stripped == "END":
            break
        match = _ASSIGN_RE.match(line)
        if match is None:
            raise ValueError(f"unparseable PDS3 label line: {line!r}")
        key, value = match.group(1), match.group(2).strip()
        if value.startswith('"'):
            while value.count('"') < 2:
                if index >= len(lines):
                    raise ValueError(f"unterminated quoted value for {key}")
                value += " " + lines[index].strip()
                index += 1
            value = re.sub(r"\s+", " ", value.strip()[1:-1]).strip()
        elif value.startswith("(") and ")" not in value:
            while ")" not in value:
                if index >= len(lines):
                    raise ValueError(f"unterminated sequence for {key}")
                value += lines[index].strip()
                index += 1
        if key == "OBJECT":
            stack.append(value)
            continue
        if key == "END_OBJECT":
            if not stack or stack[-1] != value:
                raise ValueError(f"mismatched END_OBJECT {value!r} (open: {stack})")
            stack.pop()
            continue
        path = ".".join(stack + [key])
        if path in result:
            raise ValueError(f"duplicate PDS3 key {path}")
        result[path] = value
    else:
        raise ValueError("PDS3 label has no END statement")
    if stack:
        raise ValueError(f"unclosed PDS3 OBJECT(s): {stack}")
    return result


def require(label: dict[str, str], key: str, expected: str, context: str) -> None:
    actual = label.get(key)
    if actual != expected:
        raise ValueError(f"{context}: {key}={actual!r}, expected {expected!r}")


def validate_attached_label(label: dict[str, str], row: dict) -> dict:
    """Validate an attached BIBQH label against family constants and the plan row."""
    pid = row["product_id"]
    require(label, "PDS_VERSION_ID", "PDS3", pid)
    require(label, "RECORD_TYPE", "FIXED_LENGTH", pid)
    require(label, "DATA_SET_ID", DATA_SET_ID, pid)
    require(label, "PRODUCT_ID", pid, pid)
    require(label, "TARGET_NAME", TARGET_NAME, pid)
    require(label, "INSTRUMENT_ID", "RADAR", pid)
    require(label, "INSTRUMENT_HOST_ID", "CO", pid)
    require(label, "PRODUCER_INSTITUTION_NAME", PRODUCER_INSTITUTION_NAME, pid)
    require(label, "START_TIME", row["start_time"], pid)
    require(label, "STOP_TIME", row["stop_time"], pid)
    require(label, "IMAGE.SAMPLE_TYPE", SAMPLE_TYPE, pid)
    require(label, "IMAGE.SAMPLE_BITS", SAMPLE_BITS, pid)
    require(label, "IMAGE.SCALING_FACTOR", SCALING_FACTOR, pid)
    require(label, "IMAGE.OFFSET", OFFSET, pid)
    require(label, "IMAGE.MISSING_CONSTANT", MISSING_CONSTANT, pid)
    require(label, "IMAGE_MAP_PROJECTION.MAP_RESOLUTION", MAP_RESOLUTION, pid)
    require(label, "IMAGE_MAP_PROJECTION.MAP_PROJECTION_TYPE", MAP_PROJECTION_TYPE, pid)
    for key in ("IMAGE.BANDS", "IMAGE.LINE_PREFIX_BYTES", "IMAGE.LINE_SUFFIX_BYTES"):
        if key in label and label[key] not in ("1", "0"):
            raise ValueError(f"{pid}: unexpected {key}={label[key]}")
    geometry = {
        "record_bytes": int(label["RECORD_BYTES"]),
        "file_records": int(label["FILE_RECORDS"]),
        "label_records": int(label["LABEL_RECORDS"]),
        "image_start_record": int(label["^IMAGE"]),
        "lines": int(label["IMAGE.LINES"]),
        "line_samples": int(label["IMAGE.LINE_SAMPLES"]),
        "image_checksum": int(label["IMAGE.CHECKSUM"]),
    }
    for key, value in geometry.items():
        if value != row[key]:
            raise ValueError(f"{pid}: attached label {key}={value} != pinned {row[key]}")
    check_geometry(geometry, row["img_bytes"], pid)
    return geometry


def check_geometry(geometry: dict, img_bytes: int, pid: str) -> None:
    record_bytes = geometry["record_bytes"]
    if record_bytes <= 0 or geometry["record_bytes"] * geometry["file_records"] != img_bytes:
        raise ValueError(f"{pid}: RECORD_BYTES*FILE_RECORDS != uncompressed IMG size {img_bytes}")
    if geometry["image_start_record"] != geometry["label_records"] + 1:
        raise ValueError(f"{pid}: ^IMAGE does not immediately follow the attached label records")
    pixels = geometry["lines"] * geometry["line_samples"]
    start = (geometry["image_start_record"] - 1) * record_bytes
    if pixels <= 0 or start + pixels > img_bytes:
        raise ValueError(f"{pid}: image extends past end of file")
    image_records = -(-pixels // record_bytes)
    if geometry["label_records"] + image_records != geometry["file_records"]:
        raise ValueError(f"{pid}: FILE_RECORDS != LABEL_RECORDS + ceil(LINES*LINE_SAMPLES/RECORD_BYTES)")


def image_window(geometry: dict) -> tuple[int, int]:
    start = (geometry["image_start_record"] - 1) * geometry["record_bytes"]
    return start, geometry["lines"] * geometry["line_samples"]
