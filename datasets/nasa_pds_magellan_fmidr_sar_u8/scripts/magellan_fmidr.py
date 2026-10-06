#!/usr/bin/env python3
"""Magellan F-MIDR framelet validator, builder and verifier (pure stdlib).

Natural record: one full-resolution MIDR framelet file ffNN.img with its
detached PDS3 label ffNN.lbl.  Each file holds a 2-record (2048-byte) VICAR2
header followed by 1024 lines x 1024 samples of unsigned 8-bit DN, where
DN = INT((MIN(MAX(RV,-20),30) + 20) * 5) + 1 and RV is the radar backscatter
cross section divided by the Muhleman law, in dB.  DN 0 is the single
VICAR-declared special value, MISSING DATA.

Subcommands:
  selftest            synthetic label/framelet round trip and negative cases
  validate-downloads  size/MD5 plus label/header schema of every pinned file
  build               emit one raw uint8 sample per retained framelet
  verify              independently re-derive and check the build output
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import tomllib
from pathlib import Path

DATASET_ID = "nasa_pds_magellan_fmidr_sar_u8"
SERIES_ID = "magellan_fmidr_sar_backscatter_u8"
SOURCES_SHA256 = "9b8fb2e78c08e043774348d9141ba76762f6aa8ef16770de65ec85c89f00d6a0"
DATA_SET_ID = "MGN-V-RDRS-5-MIDR-FULL-RES-V1.0"
RECORD_BYTES = 1024
FILE_RECORDS = 1026
HEADER_RECORDS = 2
IMAGE_RECORD = 3
LINES = 1024
LINE_SAMPLES = 1024
PIXELS = LINES * LINE_SAMPLES
FILE_BYTES = RECORD_BYTES * FILE_RECORDS
HEADER_BYTES = RECORD_BYTES * HEADER_RECORDS
FRAMELETS_PER_MIDR = 56
FRAMELET_COLUMNS = 8
FRAMELET_ROWS = 7
MIDR_PIXELS = FRAMELETS_PER_MIDR * PIXELS
MISSING_DN = 0
MAX_VALID_DN = 251
# Drop rule: a framelet is dropped iff more than half of its pixels are DN 0
# (MISSING DATA).  All-zero framelets are therefore always dropped.
MAX_MISSING_PIXELS = PIXELS // 2
MIN_DISTINCT_VALUES = 16
DN_LAW = "DN = INT((MIN(MAX(RV,-20),30) + 20) * 5) + 1"
HEADER_IMAGE_TEXTS = {"RADAR CROSS SECTION POWER", "NORMALIZED RADAR CROSS SECTION"}
HEADER_HI_DN = {"250", "251"}
MIDR_DIR = re.compile(r"f(\d\d)([ns])(\d{3})")
FRAMELET_NAME = re.compile(r"ff(\d\d)\.(img|lbl)")
KINDS = {
    "framelet_image",
    "framelet_label",
    "midr_histogram",
    "midr_histogram_label",
    "dataset_description_label",
}


class SchemaError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaError(message)


# --------------------------------------------------------------------------
# PDS3 label parsing
# --------------------------------------------------------------------------

def parse_pds3_label(text: str) -> dict:
    """Parse a PDS3 ODL label into nested dicts.

    Each object dict maps KEY -> raw value string and stores child objects in
    ``_objects`` as (name, dict) pairs.  Comments are removed; quoted values
    may span lines.  Duplicate keys within one object are an error.
    """
    text = re.sub(r"/\*.*?\*/", " ", text.replace("\r", ""), flags=re.S)
    root: dict = {"_objects": []}
    stack = [root]
    pos = 0
    length = len(text)
    key_re = re.compile(r"\s*(\^?[A-Za-z0-9_:]+)\s*=\s*")
    end_re = re.compile(r"\s*(END_OBJECT|END)\b[ \t]*(=[ \t]*\S+)?")
    while True:
        while pos < length and text[pos].isspace():
            pos += 1
        if pos >= length:
            raise SchemaError("label has no END statement")
        end = end_re.match(text, pos)
        if end and not key_re.match(text, pos) or (end and end.group(1) == "END_OBJECT"):
            pos = end.end()
            if end.group(1) == "END":
                break
            require(len(stack) > 1, "END_OBJECT without OBJECT")
            stack.pop()
            continue
        match = key_re.match(text, pos)
        require(match is not None, f"unparseable label text near offset {pos}: {text[pos:pos + 40]!r}")
        key = match.group(1)
        pos = match.end()
        opener = text[pos] if pos < length else ""
        closers = {'"': '"', "'": "'", "(": ")", "{": "}"}
        if opener in closers:
            close = text.find(closers[opener], pos + 1)
            require(close >= 0, f"unterminated value for {key}")
            value = text[pos:close + 1]
            pos = close + 1
            line_end = text.find("\n", pos)
            line_end = length if line_end < 0 else line_end
            tail = text[pos:line_end].strip()
            if tail:
                value = f"{value} {tail}"
            pos = line_end
        else:
            line_end = text.find("\n", pos)
            line_end = length if line_end < 0 else line_end
            value = text[pos:line_end].strip()
            pos = line_end
        current = stack[-1]
        if key == "OBJECT":
            child: dict = {"_objects": [], "_name": value}
            current["_objects"].append((value, child))
            stack.append(child)
            continue
        require(key not in current, f"duplicate label key {key}")
        current[key] = value
    require(len(stack) == 1, "unbalanced OBJECT/END_OBJECT")
    return root


def label_object(label: dict, name: str) -> dict:
    found = [obj for obj_name, obj in label["_objects"] if obj_name == name]
    require(len(found) == 1, f"label must contain exactly one {name} object")
    return found[0]


def text_value(obj: dict, key: str) -> str:
    require(key in obj, f"label key {key} missing")
    value = obj[key].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return " ".join(value.split())


def int_value(obj: dict, key: str) -> int:
    value = text_value(obj, key)
    require(re.fullmatch(r"[+-]?\d+", value) is not None, f"label key {key} is not an integer: {value!r}")
    return int(value)


def float_value(obj: dict, key: str) -> float:
    value = text_value(obj, key).split("<")[0].strip()
    try:
        return float(value)
    except ValueError as exc:
        raise SchemaError(f"label key {key} is not numeric: {value!r}") from exc


def pointer_value(obj: dict, key: str) -> tuple[str, int]:
    match = re.fullmatch(r'\(\s*"([^"]+)"\s*,\s*(\d+)\s*\)', obj.get(key, "").strip())
    require(match is not None, f"label pointer {key} malformed: {obj.get(key)!r}")
    return match.group(1), int(match.group(2))


def midr_image_id(midr: str) -> str:
    match = MIDR_DIR.fullmatch(midr)
    require(match is not None, f"not an F-MIDR directory name: {midr}")
    return f"F-MIDR.{match.group(1)}{match.group(2).upper()}{match.group(3)}"


def check_framelet_label(label_text: str, midr: str, number: int) -> dict:
    label = parse_pds3_label(label_text)
    expected_file = f"FF{number:02d}.IMG"
    require(text_value(label, "RECORD_TYPE") == "FIXED_LENGTH", "RECORD_TYPE must be FIXED_LENGTH")
    require(int_value(label, "RECORD_BYTES") == RECORD_BYTES, "RECORD_BYTES must be 1024")
    require(int_value(label, "FILE_RECORDS") == FILE_RECORDS, f"FILE_RECORDS must be {FILE_RECORDS}")
    header_file, header_record = pointer_value(label, "^IMAGE_HEADER")
    image_file, image_record = pointer_value(label, "^IMAGE")
    # The label names the file in upper case; the bucket key is lower case.
    require(header_file.upper() == expected_file and image_file.upper() == expected_file,
            f"label pointers name {header_file}/{image_file}, expected {expected_file}")
    require(header_record == 1 and image_record == IMAGE_RECORD, "pointer records must be 1 and 3")
    require(text_value(label, "DATA_SET_ID") == DATA_SET_ID, "DATA_SET_ID mismatch")
    require(text_value(label, "SPACECRAFT_NAME") == "MAGELLAN", "SPACECRAFT_NAME mismatch")
    require(text_value(label, "TARGET_NAME") == "VENUS", "TARGET_NAME mismatch")
    require(text_value(label, "INSTRUMENT_NAME") == "RADAR SYSTEM", "INSTRUMENT_NAME mismatch")
    require(text_value(label, "MISSION_PHASE_NAME") == "PRIMARY_MISSION", "MISSION_PHASE_NAME mismatch")
    image_id = text_value(label, "IMAGE_ID")
    require(re.fullmatch(re.escape(midr_image_id(midr)) + r";\d+", image_id) is not None,
            f"IMAGE_ID {image_id!r} does not match directory {midr}")
    header = label_object(label, "IMAGE_HEADER")
    require(text_value(header, "TYPE") == "VICAR2", "IMAGE_HEADER TYPE must be VICAR2")
    require(int_value(header, "BYTES") == RECORD_BYTES, "IMAGE_HEADER BYTES must be 1024")
    require(int_value(header, "RECORDS") == HEADER_RECORDS, "IMAGE_HEADER RECORDS must be 2")
    image = label_object(label, "IMAGE")
    require(int_value(image, "LINES") == LINES, "IMAGE LINES must be 1024")
    require(int_value(image, "LINE_SAMPLES") == LINE_SAMPLES, "IMAGE LINE_SAMPLES must be 1024")
    require(text_value(image, "SAMPLE_TYPE") == "UNSIGNED_INTEGER", "SAMPLE_TYPE must be UNSIGNED_INTEGER")
    require(int_value(image, "SAMPLE_BITS") == 8, "SAMPLE_BITS must be 8")
    require(DN_LAW in text_value(image, "NOTE"), "IMAGE NOTE does not state the pinned DN law")
    projection = label_object(label, "IMAGE_MAP_PROJECTION_CATALOG")
    require(text_value(projection, "DATA_SET_ID") == DATA_SET_ID, "projection DATA_SET_ID mismatch")
    require(text_value(projection, "IMAGE_ID") == image_id, "projection IMAGE_ID mismatch")
    require(text_value(projection, "MAP_PROJECTION_TYPE") == "SINUSOIDAL", "projection must be SINUSOIDAL")
    require(float_value(projection, "MAP_SCALE") == 75.0, "MAP_SCALE must be 75 m/pixel")
    require(float_value(projection, "MAP_RESOLUTION") == 1407.4, "MAP_RESOLUTION must be 1407.4 pixel/deg")
    require(int_value(projection, "X_AXIS_LAST_PIXEL") == LINE_SAMPLES, "X_AXIS_LAST_PIXEL must be 1024")
    require(int_value(projection, "Y_AXIS_LAST_PIXEL") == LINES, "Y_AXIS_LAST_PIXEL must be 1024")
    return {
        "image_id": image_id,
        "minimum_latitude": float_value(projection, "MINIMUM_LATITUDE"),
        "maximum_latitude": float_value(projection, "MAXIMUM_LATITUDE"),
        "minimum_longitude": float_value(projection, "MINIMUM_LONGITUDE"),
        "maximum_longitude": float_value(projection, "MAXIMUM_LONGITUDE"),
    }


def check_histogram_label(label_text: str, midr: str) -> None:
    label = parse_pds3_label(label_text)
    require(int_value(label, "RECORD_BYTES") == 1024 and int_value(label, "FILE_RECORDS") == 1,
            "HIST.LBL must declare one 1024-byte record")
    require(text_value(label, "^IMAGE_HISTOGRAM").upper() == "HIST.TAB", "HIST.LBL pointer mismatch")
    image_id = text_value(label, "IMAGE_ID").upper()
    require(re.fullmatch(re.escape(midr_image_id(midr)) + r";\d+", image_id) is not None, "HIST.LBL IMAGE_ID mismatch")
    hist = label_object(label, "IMAGE_HISTOGRAM")
    require(int_value(hist, "ITEMS") == 256 and int_value(hist, "ITEM_BYTES") == 4, "histogram must be 256 x 4 bytes")
    require(text_value(hist, "DATA_TYPE") == "VAX_INTEGER", "histogram DATA_TYPE must be VAX_INTEGER")


def read_histogram(raw: bytes) -> list[int]:
    require(len(raw) == 1024, "HIST.TAB must be 1024 bytes")
    values = list(struct.unpack("<256I", raw))  # VAX_INTEGER = little-endian
    require(sum(values) == MIDR_PIXELS, f"HIST.TAB total {sum(values)} != {MIDR_PIXELS}")
    return values


# --------------------------------------------------------------------------
# VICAR2 header and pixel payload
# --------------------------------------------------------------------------

def parse_vicar_header(raw: bytes) -> tuple[dict, dict]:
    text = raw.decode("latin-1")
    match = re.match(r"LBLSIZE=\s*(\d+)\s", text)
    require(match is not None, "VICAR header must start with LBLSIZE=")
    lblsize = int(match.group(1))
    require(lblsize == HEADER_BYTES, f"VICAR LBLSIZE {lblsize} != {HEADER_BYTES}")
    text = text[:lblsize].split("\x00", 1)[0]
    first: dict = {}
    every: dict = collections.defaultdict(list)
    for key, value in re.findall(r"([A-Z][A-Z0-9_]*)=\s*('(?:[^']|'')*'|[^\s']+)", text):
        if value.startswith("'"):
            value = value[1:-1].replace("''", "'")
        every[key].append(value)
        first.setdefault(key, value)
    return first, every


def check_vicar_header(raw: bytes, image_id: str, number: int) -> dict:
    first, every = parse_vicar_header(raw)
    expected = {
        "FORMAT": "BYTE",
        "TYPE": "IMAGE",
        "ORG": "BSQ",
        "DIM": "3",
        "EOL": "0",
        "RECSIZE": str(RECORD_BYTES),
        "NL": str(LINES),
        "NS": str(LINE_SAMPLES),
        "NB": "1",
        "NBB": "0",
        "NLB": "0",
        "PRODTYPE": "F-MIDR",
        "DN_UNITS": "DECIBELS",
        "N_SPDN": "1",
        "SPDN_1": str(MISSING_DN),
        "M_SPDN_1": "MISSING DATA",
        "LOW_DN": "1",
        "LOW_REP": "-20.0",
        "HI_REP": "30.0",
        "SUBFRAME": str(number),
        "SUBF_ROW": str((number - 1) // FRAMELET_COLUMNS + 1),
        "SUBF_COL": str((number - 1) % FRAMELET_COLUMNS + 1),
        "SUBF_TOT": str(FRAMELETS_PER_MIDR),
        "PRODUCT": image_id,
    }
    for key, value in expected.items():
        require(len(every.get(key, [])) == 1, f"VICAR key {key} must occur exactly once")
        require(first[key] == value, f"VICAR {key}={first[key]!r}, expected {value!r}")
    require(len(every.get("IMAGE", [])) == 1 and first["IMAGE"] in HEADER_IMAGE_TEXTS,
            f"VICAR IMAGE={first.get('IMAGE')!r} not an F-MIDR backscatter header")
    require(len(every.get("HI_DN", [])) == 1 and first["HI_DN"] in HEADER_HI_DN, "VICAR HI_DN must be 250 or 251")
    require(first.get("SEAM") in {"CORRECTED", "UNCORRECTED"}, "VICAR SEAM must be CORRECTED or UNCORRECTED")
    return {"vicar_image": first["IMAGE"], "seam": first["SEAM"]}


def framelet_pixels(image: bytes, image_id: str, number: int) -> tuple[bytes, dict]:
    require(len(image) == FILE_BYTES, f"framelet size {len(image)} != {FILE_BYTES}")
    header = check_vicar_header(image[:HEADER_BYTES], image_id, number)
    start = (IMAGE_RECORD - 1) * RECORD_BYTES
    pixels = image[start:start + PIXELS]
    require(len(pixels) == PIXELS, "framelet pixel payload truncated")
    return pixels, header


def histogram_by_counter(pixels: bytes) -> list[int]:
    counts = collections.Counter(pixels)
    return [counts.get(value, 0) for value in range(256)]


def histogram_by_count(pixels: bytes) -> list[int]:
    return [pixels.count(bytes((value,))) for value in range(256)]


def pixel_stats(hist: list[int]) -> dict:
    present = [value for value, count in enumerate(hist) if count]
    total = sum(hist)
    return {
        "min_value": present[0],
        "max_value": present[-1],
        "mean_value": round(sum(value * count for value, count in enumerate(hist)) / total, 6),
        "zero_count": hist[MISSING_DN],
        "distinct_values": len(present),
    }


def keep_framelet(hist: list[int]) -> bool:
    return hist[MISSING_DN] <= MAX_MISSING_PIXELS


def check_retained(stats: dict, where: str) -> None:
    require(stats["max_value"] <= MAX_VALID_DN, f"{where}: DN {stats['max_value']} exceeds the DN law maximum {MAX_VALID_DN}")
    require(stats["min_value"] != stats["max_value"], f"{where}: constant framelet")
    require(stats["distinct_values"] >= MIN_DISTINCT_VALUES, f"{where}: only {stats['distinct_values']} distinct DN values")


# --------------------------------------------------------------------------
# Source plan
# --------------------------------------------------------------------------

def load_sources(path: Path) -> list[dict]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    require(digest == SOURCES_SHA256, f"sources.tsv identity changed: sha256={digest}")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    seen = set()
    for row in rows:
        require(row["kind"] in KINDS, f"unknown source kind {row['kind']}")
        require(re.fullmatch(r"mg_0\d{3}", row["volume"]) is not None, "bad volume")
        require(re.fullmatch(r"(f\d\d[ns]\d{3}|label)", row["directory"]) is not None, "bad directory")
        require(re.fullmatch(r"[a-z0-9_]+\.(img|lbl|tab)", row["file"]) is not None, "bad file name")
        require(re.fullmatch(r"[0-9a-f]{32}", row["md5"]) is not None, "bad md5")
        key = (row["volume"], row["directory"], row["file"])
        require(key not in seen, f"duplicate source {key}")
        seen.add(key)
        row["size_bytes"] = int(row["size_bytes"])
    return rows


def midr_groups(rows: list[dict]) -> list[tuple[str, str]]:
    groups = sorted({(r["volume"], r["directory"]) for r in rows if r["kind"] == "framelet_image"})
    for volume, midr in groups:
        members = {r["file"] for r in rows if (r["volume"], r["directory"]) == (volume, midr)}
        expected = {f"ff{n:02d}.{s}" for n in range(1, FRAMELETS_PER_MIDR + 1) for s in ("img", "lbl")}
        require(expected | {"hist.tab", "hist.lbl"} == members, f"{volume}/{midr}: incomplete source plan")
    return groups


def local_path(download_dir: Path, row: dict) -> Path:
    return download_dir / row["volume"] / row["directory"] / row["file"]


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_download(download_dir: Path, row: dict) -> Path:
    path = local_path(download_dir, row)
    require(path.is_file(), f"missing download {path}")
    require(path.stat().st_size == row["size_bytes"], f"{path}: size {path.stat().st_size} != {row['size_bytes']}")
    require(md5_file(path) == row["md5"], f"{path}: MD5 mismatch")
    return path


def inspect_midr(download_dir: Path, volume: str, midr: str, hist_fn) -> tuple[list[dict], list[int], list[int]]:
    """Validate one MIDR's 56 framelets; return records, summed histogram, HIST.TAB histogram."""
    base = download_dir / volume / midr
    check_histogram_label((base / "hist.lbl").read_text(encoding="latin-1"), midr)
    published = read_histogram((base / "hist.tab").read_bytes())
    total = [0] * 256
    records = []
    for number in range(1, FRAMELETS_PER_MIDR + 1):
        stem = f"ff{number:02d}"
        meta = check_framelet_label((base / f"{stem}.lbl").read_text(encoding="latin-1"), midr, number)
        pixels, header = framelet_pixels((base / f"{stem}.img").read_bytes(), meta["image_id"], number)
        hist = hist_fn(pixels)
        total = [a + b for a, b in zip(total, hist)]
        records.append({
            "volume": volume,
            "midr_directory": midr,
            "framelet": number,
            "framelet_row": (number - 1) // FRAMELET_COLUMNS + 1,
            "framelet_col": (number - 1) % FRAMELET_COLUMNS + 1,
            **meta,
            **header,
            **pixel_stats(hist),
            "keep": keep_framelet(hist),
            "sha256": hashlib.sha256(pixels).hexdigest(),
            "pixels": pixels,
        })
    return records, total, published


def sample_rel_path(record: dict) -> str:
    return (f"samples/{DATASET_ID}/{SERIES_ID}/"
            f"{record['volume']}_{record['midr_directory']}_ff{record['framelet']:02d}.u8")


INDEX_FIELDS = ("volume", "midr_directory", "framelet", "framelet_row", "framelet_col", "image_id",
                "vicar_image", "seam", "minimum_latitude", "maximum_latitude", "minimum_longitude",
                "maximum_longitude", "min_value", "max_value", "mean_value", "zero_count",
                "distinct_values", "sha256")


def index_row(record: dict) -> dict:
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": sample_rel_path(record),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": PIXELS,
        "value_count": PIXELS,
        "sample_shape": [LINES, LINE_SAMPLES],
        "sample_axes": ["line", "sample"],
    }
    row.update({field: record[field] for field in INDEX_FIELDS})
    row["source_image"] = f"{record['volume']}/{record['midr_directory']}/ff{record['framelet']:02d}.img"
    return row


def aggregate_digest(rows: list[dict]) -> str:
    text = "".join(f"{r['sample_path']}\t{r['sha256']}\n" for r in sorted(rows, key=lambda r: r["sample_path"]))
    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_validate_downloads(args: argparse.Namespace) -> None:
    rows = load_sources(Path(args.sources))
    download_dir = Path(args.download_dir)
    for row in rows:
        check_download(download_dir, row)
    description = [r for r in rows if r["kind"] == "dataset_description_label"]
    require(len(description) == 1, "exactly one dataset description label expected")
    text = local_path(download_dir, description[0]).read_text(encoding="latin-1")
    require(DATA_SET_ID in text and "Full-resolution Mosaic Image Data" in " ".join(text.split()),
            "dataset description label does not describe the F-MIDR data set")
    framelets = 0
    for volume, midr in midr_groups(rows):
        base = download_dir / volume / midr
        check_histogram_label((base / "hist.lbl").read_text(encoding="latin-1"), midr)
        read_histogram((base / "hist.tab").read_bytes())
        for number in range(1, FRAMELETS_PER_MIDR + 1):
            meta = check_framelet_label((base / f"ff{number:02d}.lbl").read_text(encoding="latin-1"), midr, number)
            with (base / f"ff{number:02d}.img").open("rb") as handle:
                check_vicar_header(handle.read(HEADER_BYTES), meta["image_id"], number)
            framelets += 1
    print(f"downloads_valid=1 files={len(rows)} bytes={sum(r['size_bytes'] for r in rows)} framelets={framelets}")


def cmd_build(args: argparse.Namespace) -> None:
    rows = load_sources(Path(args.sources))
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    for row in rows:
        check_download(download_dir, row)
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    index_rows = []
    per_midr = {}
    dropped = []
    for volume, midr in midr_groups(rows):
        records, total, published = inspect_midr(download_dir, volume, midr, histogram_by_counter)
        require(total == published, f"{volume}/{midr}: framelet histograms do not sum to HIST.TAB")
        kept = 0
        for record in records:
            where = f"{volume}/{midr}/ff{record['framelet']:02d}"
            if not record["keep"]:
                dropped.append(where)
                continue
            check_retained(record, where)
            out = data_root / sample_rel_path(record)
            tmp = out.with_suffix(".tmp")
            tmp.write_bytes(record["pixels"])
            os.replace(tmp, out)
            index_rows.append(index_row(record))
            kept += 1
        per_midr[f"{volume}/{midr}"] = {
            "image_id": records[0]["image_id"],
            "kept": kept,
            "dropped": FRAMELETS_PER_MIDR - kept,
            "midr_missing_fraction": round(total[MISSING_DN] / MIDR_PIXELS, 6),
            "histogram_matches_hist_tab": True,
            "vicar_image": records[0]["vicar_image"],
            "seam": records[0]["seam"],
        }
        print(f"midr {volume}/{midr} kept={kept} dropped={FRAMELETS_PER_MIDR - kept} hist_tab_match=1")
    require(index_rows, "no framelets retained")
    index_rows.sort(key=lambda r: r["sample_path"])
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for row in index_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "midrs": per_midr,
        "framelets_inspected": FRAMELETS_PER_MIDR * len(per_midr),
        "samples": len(index_rows),
        "total_size_bytes": PIXELS * len(index_rows),
        "dropped_framelets": dropped,
        "drop_rule": f"drop iff DN-0 (MISSING DATA) pixel count > {MAX_MISSING_PIXELS}",
        "aggregate_sha256": aggregate_digest(index_rows),
    }
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"build_ok samples={len(index_rows)} bytes={PIXELS * len(index_rows)} dropped={len(dropped)} "
          f"aggregate_sha256={stats['aggregate_sha256']}")


def cmd_verify(args: argparse.Namespace) -> None:
    rows = load_sources(Path(args.sources))
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    require(len(series) == 1 and series[0]["role"] == "primary", "manifest primary series missing")
    series = series[0]
    for row in rows:
        check_download(download_dir, row)

    # Independent re-derivation from the downloads (histograms via bytes.count).
    derived = {}
    dropped = []
    for volume, midr in midr_groups(rows):
        records, total, published = inspect_midr(download_dir, volume, midr, histogram_by_count)
        require(total == published, f"{volume}/{midr}: framelet histograms do not sum to HIST.TAB")
        for record in records:
            where = f"{volume}/{midr}/ff{record['framelet']:02d}"
            if record["keep"]:
                check_retained(record, where)
                derived[sample_rel_path(record)] = record
            else:
                dropped.append(where)

    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    paths = [r["sample_path"] for r in index_rows]
    require(len(paths) == len(set(paths)), "duplicate index sample paths")
    require(set(paths) == set(derived), "indexed samples differ from the re-derived retained framelets")
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{p.name}" for p in series_dir.iterdir()}
    require(on_disk == set(paths), "sample directory holds files that are not indexed (or vice versa)")
    digests = set()
    for row in index_rows:
        record = derived[row["sample_path"]]
        want = index_row(record)
        for key, value in want.items():
            require(row.get(key) == value, f"{row['sample_path']}: index field {key}={row.get(key)!r}, expected {value!r}")
        data = (data_root / row["sample_path"]).read_bytes()
        require(data == record["pixels"], f"{row['sample_path']}: sample bytes differ from the source IMAGE payload")
        require(hashlib.sha256(data).hexdigest() == row["sha256"], f"{row['sample_path']}: sha256 mismatch")
        require(row["zero_count"] <= MAX_MISSING_PIXELS, f"{row['sample_path']}: violates drop rule")
        digests.add(row["sha256"])
    require(len(digests) == len(index_rows), "duplicate sample payloads")
    total_bytes = PIXELS * len(index_rows)
    require(series["sample_count"] == len(index_rows), f"manifest sample_count {series['sample_count']} != {len(index_rows)}")
    require(series["total_size_bytes"] == total_bytes, f"manifest total_size_bytes {series['total_size_bytes']} != {total_bytes}")
    require(sorted(dropped) == sorted(expected["dropped_framelets"]), f"dropped framelets {dropped} differ from pinned list")
    require(expected["sample_count"] == len(index_rows), "pinned sample count mismatch")
    digest = aggregate_digest(index_rows)
    require(bool(expected.get("aggregate_sha256")), f"expected_output.json has no pinned aggregate_sha256 (realized {digest})")
    require(expected["aggregate_sha256"] == digest, f"aggregate sha256 {digest} differs from pinned value")
    summary = {
        "verified": True,
        "samples": len(index_rows),
        "total_size_bytes": total_bytes,
        "dropped_framelets": sorted(dropped),
        "aggregate_sha256": digest,
        "midrs": sorted({f"{r['volume']}/{r['midr_directory']}" for r in index_rows}),
        "zero_fraction_retained": round(sum(r["zero_count"] for r in index_rows) / total_bytes, 6),
        "min_distinct_values": min(r["distinct_values"] for r in index_rows),
        "mean_value_range": [min(r["mean_value"] for r in index_rows), max(r["mean_value"] for r in index_rows)],
    }
    out = data_root / "filtered" / DATASET_ID / "verify_stats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"verify_ok samples={len(index_rows)} bytes={total_bytes} dropped={len(dropped)} aggregate_sha256={digest}")


# --------------------------------------------------------------------------
# Self-test on synthetic inputs
# --------------------------------------------------------------------------

LABEL_TEMPLATE = """CCSD3ZF0000100000001NJPL3IF0PDS200000001 = SFDU_LABEL
/*    Framelet file format, size and location   */
RECORD_TYPE                   = FIXED_LENGTH
RECORD_BYTES                  = 1024
FILE_RECORDS                  = {file_records}
^IMAGE_HEADER                 = ("FF{nn}.IMG",1)
^IMAGE                        = ("FF{nn}.IMG",3)
/*    Framelet description       */
DATA_SET_ID                   = 'MGN-V-RDRS-5-MIDR-FULL-RES-V1.0'
SPACECRAFT_NAME               = MAGELLAN
MISSION_PHASE_NAME            = PRIMARY_MISSION
TARGET_NAME                   = VENUS
IMAGE_ID                      = '{image_id};1'
INSTRUMENT_NAME               = 'RADAR SYSTEM'
OBJECT                        = IMAGE_HEADER
 TYPE                         = VICAR2
 BYTES                        = 1024
 RECORDS                      = 2
END_OBJECT
OBJECT                        = IMAGE
 LINES                        = 1024
 LINE_SAMPLES                 = 1024
 SAMPLE_TYPE                  = UNSIGNED_INTEGER
 SAMPLE_BITS                  = 8
 NOTE                         = "
     DN = INT((MIN(MAX(RV,-20),30) + 20) * 5) + 1,
 where RV = radar crossection/area divided by the
 Muhleman Law and converted to decibels."
END_OBJECT

OBJECT                        = IMAGE_MAP_PROJECTION_CATALOG
 ^DATA_SET_MAP_PROJECT_CATALOG = 'DSMAPF.LBL'
 DATA_SET_ID                  = 'MGN-V-RDRS-5-MIDR-FULL-RES-V1.0'
 IMAGE_ID                     = '{image_id};1'
 MAP_PROJECTION_TYPE          = SINUSOIDAL
 MAP_RESOLUTION               = 1407.4 <PIXEL/DEG>
 MAP_SCALE                    = 75 <M/PIXEL>
 MAXIMUM_LATITUDE             = 37.5452
 MAXIMUM_LONGITUDE            = 280.7211
 MINIMUM_LATITUDE             = 36.8187
 MINIMUM_LONGITUDE            = 279.7785
 X_AXIS_LAST_PIXEL            = 1024
 Y_AXIS_LAST_PIXEL            = 1024
END_OBJECT
END
"""


def synthetic_label(midr: str, number: int, file_records: int = FILE_RECORDS) -> str:
    text = LABEL_TEMPLATE.format(file_records=file_records, nn=f"{number:02d}", image_id=midr_image_id(midr))
    return "".join(line.ljust(78) + "\r\n" for line in text.splitlines())


def synthetic_header(image_id: str, number: int, subframe: int | None = None) -> bytes:
    subframe = number if subframe is None else subframe
    text = (f"LBLSIZE={HEADER_BYTES}            FORMAT='BYTE'  TYPE='IMAGE'  BUFSIZ=20480  DIM=3  EOL=0  "
            f"RECSIZE=1024  ORG='BSQ'  NL=1024  NS=1024  NB=1  N1=1024  N2=1024  N3=1  N4=0  NBB=0  NLB=0  "
            f"HOST='VAX-VMS'  TASK='LOGMOS'  USER='X'  DAT_TIM='Fri Jul 12 11:42:54 1991'  SEAM='CORRECTED'  "
            f"IMAGE='NORMALIZED RADAR CROSS SECTION'  DN_UNITS='DECIBELS'  M_SPDN_1='MISSING DATA'  "
            f"LOW_REP=-20.0  HI_REP=30.0  LOW_DN=1  HI_DN=251  N_SPDN=1  SPDN_1=0  TASK='SFASTMOS'  "
            f"USER='Y'  DAT_TIM='Thu Oct  3 05:43:30 1991'  PRODUCT='{image_id}'  SUBFRAME={subframe}  "
            f"SUBF_ROW={(subframe - 1) // 8 + 1}  SUBF_COL={(subframe - 1) % 8 + 1}  SUBF_TOT=56  "
            f"PRODTYPE='F-MIDR'  TASK='COPY'  USER='Z'  DAT_TIM='Thu Oct  3 06:28:22 1991'  ")
    raw = text.encode("latin-1")
    return raw + b"\x00" * (HEADER_BYTES - len(raw))


def expect_failure(func, *args) -> None:
    try:
        func(*args)
    except SchemaError:
        return
    raise AssertionError(f"{func.__name__} accepted an invalid input")


def cmd_selftest(_: argparse.Namespace) -> None:
    midr, number = "f35n283", 28
    image_id = midr_image_id(midr) + ";1"
    meta = check_framelet_label(synthetic_label(midr, number), midr, number)
    assert meta["image_id"] == image_id and meta["maximum_latitude"] == 37.5452
    pixels = bytes(((i * 7 + (i >> 10) * 3) % 251) + 1 for i in range(PIXELS))
    image = synthetic_header(image_id, number) + pixels
    got, header = framelet_pixels(image, image_id, number)
    assert got == pixels and header["seam"] == "CORRECTED"
    assert histogram_by_counter(pixels) == histogram_by_count(pixels)
    stats = pixel_stats(histogram_by_count(pixels))
    assert stats["min_value"] == 1 and stats["max_value"] == 251 and stats["zero_count"] == 0
    check_retained(stats, "synthetic")
    # Negative cases: wrong record count, wrong framelet, wrong pointer case map, truncation.
    expect_failure(check_framelet_label, synthetic_label(midr, number, FILE_RECORDS - 1), midr, number)
    expect_failure(check_framelet_label, synthetic_label(midr, number), midr, number + 1)
    expect_failure(check_framelet_label, synthetic_label(midr, number), "f35n284", number)
    expect_failure(framelet_pixels, synthetic_header(image_id, number, subframe=27) + pixels, image_id, number)
    expect_failure(framelet_pixels, image[:-1], image_id, number)
    bad = bytearray(pixels)
    bad[5] = 252
    expect_failure(check_retained, pixel_stats(histogram_by_count(bytes(bad))), "synthetic")
    expect_failure(check_retained, pixel_stats(histogram_by_count(bytes([9]) * PIXELS)), "synthetic")
    # Drop-rule boundary: exactly half missing is kept, one more pixel is dropped.
    half = bytes(MAX_MISSING_PIXELS) + pixels[MAX_MISSING_PIXELS:]
    assert keep_framelet(histogram_by_count(half))
    over = bytes(MAX_MISSING_PIXELS + 1) + pixels[MAX_MISSING_PIXELS + 1:]
    assert not keep_framelet(histogram_by_count(over))
    assert not keep_framelet(histogram_by_count(bytes(PIXELS)))
    # Histogram table decode.
    hist = [0] * 256
    hist[0], hist[100] = 5, MIDR_PIXELS - 5
    assert read_histogram(struct.pack("<256I", *hist)) == hist
    expect_failure(read_histogram, struct.pack("<256I", *([1] * 256)))
    print("selftest_ok=1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("selftest")
    p.set_defaults(func=cmd_selftest)
    for name, func in (("validate-downloads", cmd_validate_downloads), ("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--sources", required=True)
        p.add_argument("--download-dir", required=True)
        if name != "validate-downloads":
            p.add_argument("--data-root", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
            p.add_argument("--expected", required=True)
        p.set_defaults(func=func)
    args = parser.parse_args()
    try:
        args.func(args)
    except SchemaError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
