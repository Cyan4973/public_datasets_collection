#!/usr/bin/env python3
"""EMPIAR-13192 Carotid2 SBF-SEM block-face slices: validate, build, verify.

Pure standard library. Each source file is a classic little-endian TIFF
written by the Thermo Fisher (FEI) xT acquisition software of a VolumeScope
serial block-face SEM: an 8-byte header, one uncompressed 6144x4096 uint8
backscatter image stored as 2048 contiguous 2-row strips starting at byte 8,
then a single IFD whose out-of-line arrays and FEI metadata tags
(34682 INI text, 34683 XML) run to end of file.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import html
import json
import re
import shutil
import statistics
import struct
import sys
import tomllib
import zlib
from pathlib import Path
from typing import Callable


DATASET_ID = "empiar_13192_sbfsem_vessel_slices_u8"
SERIES_ID = "carotid2_sbfsem_bse_u8"
ENTRY_KEY = "EMPIAR-13192"
ENTRY_TITLE = "Volume electron microscopy reveals heterogeneity of the hemostatic response in veins and arteries"
ENTRY_DOI = "10.6019/EMPIAR-13192"
IMAGESET_DIR = "data/Stalker_SBF-SEM/Carotid2"
BASE_URL = "https://ftp.ebi.ac.uk/empiar/world_availability/13192/data/Stalker_SBF-SEM/Carotid2"
LICENSE_SENTENCE = (
    "All data in EMPIAR is freely and publicly available to the global community under the CC0 license"
)

WIDTH = 6144
HEIGHT = 4096
PIXEL_BYTES = WIDTH * HEIGHT  # 25,165,824
IFD_OFFSET = 8 + PIXEL_BYTES  # 25,165,832
HEADER = b"II*\x00" + struct.pack("<I", IFD_OFFSET)
ROWS_PER_STRIP = 2
STRIP_COUNT = HEIGHT // ROWS_PER_STRIP  # 2048
STRIP_BYTES = WIDTH * ROWS_PER_STRIP  # 12,288
VOLUME_SLICES = 1250
Z_START = 10
Z_STEP = 40
SELECTED_Z = tuple(range(Z_START, VOLUME_SLICES + 1, Z_STEP))  # 10, 50, ..., 1250 -> 32 slices
PINS_PATH = Path(__file__).with_name("carotid2_slices.tsv")
PIN_FIELDS = ["z", "file_name", "size_bytes", "metadata_sha256", "acquisition_datetime", "file_sha256"]

EXPECTED_TAGS = (254, 256, 257, 258, 259, 262, 273, 277, 278, 279, 282, 283, 296, 34682, 34683)
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
TYPE_FORMATS = {1: "B", 3: "H", 4: "I", 8: "h", 9: "i", 16: "Q"}

# FEI [section] key=value invariants that every selected slice must carry.
FEI_REQUIRED = {
    ("System", "Type"): "SEM",
    ("System", "SystemType"): "Volumescope",
    ("Image", "ResolutionX"): "6144",
    ("Image", "ResolutionY"): "4096",
    ("Image", "PostProcessing"): "None",
    ("Image", "Transformation"): "None",
    ("Image", "DriftCorrected"): "Off",
    ("Image", "ZoomFactor"): "1.0",
    ("PrivateFei", "DatabarHeight"): "0",
    ("PrivateFei", "BitShift"): "0",
    ("Scan", "PixelWidth"): "6.5e-008",
    ("Scan", "PixelHeight"): "6.5e-008",
    ("Beam", "HV"): "3000",
    ("Detectors", "Number"): "1",
    ("Detectors", "Name"): "VS DBS",
    ("VS DBS", "Signal"): "BSE",
}
# Checked after collapsing inter-tag whitespace: full-frame scan, no reduced area.
XML_REQUIRED = (
    "<InstrumentClass>Volumescope</InstrumentClass>",
    "<ScanSize><Width>6144</Width><Height>4096</Height></ScanSize>",
    "<ScanArea><X>0</X><Y>0</Y><Width>6144</Width><Height>4096</Height></ScanArea>",
)

# SHA-256 over "<sample file name>\t<sample sha256>\n" lines in z order, from the
# first verified build (2026-10-06); build and verify both require it.
EXPECTED_OUTPUT_DIGEST = "6aabf0cefce281fc39d0fe24e9d7a229b3a474d34956a1c3672f72933afce1af"

# Degeneracy floor applied identically by build and verify.
MIN_DISTINCT = 64
MAX_MODAL_FRACTION = 0.5

ReadAt = Callable[[int, int], bytes]


class SourceError(Exception):
    pass


# ---------------------------------------------------------------- pins / docs


def file_name(z: int) -> str:
    return f"Carotid2_Z{z:04d}.tif"


def load_pins() -> dict[int, dict[str, str]]:
    with PINS_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or list(rows[0].keys()) != PIN_FIELDS:
        raise SourceError(f"unexpected pin columns in {PINS_PATH.name}")
    for row in rows:  # "-" marks a whole-file hash not pinned yet
        row["file_sha256"] = "" if row["file_sha256"] == "-" else row["file_sha256"]
    pins = {int(row["z"]): row for row in rows}
    if tuple(sorted(pins)) != SELECTED_Z or len(rows) != len(SELECTED_Z):
        raise SourceError("pin table does not list exactly the selected slices")
    for z, row in pins.items():
        if row["file_name"] != file_name(z) or not re.fullmatch(r"[0-9a-f]{64}", row["metadata_sha256"]):
            raise SourceError(f"malformed pin row for z={z}")
        if row["file_sha256"] and not re.fullmatch(r"[0-9a-f]{64}", row["file_sha256"]):
            raise SourceError(f"malformed file_sha256 pin for z={z}")
    stamps = [pins[z]["acquisition_datetime"] for z in SELECTED_Z]
    if any(not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", s) for s in stamps) or stamps != sorted(set(stamps)):
        raise SourceError("pinned acquisition timestamps are not strictly increasing with z")
    return pins


def check_entry(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data.get(ENTRY_KEY)
    if not isinstance(entry, dict):
        raise SourceError("EMPIAR API response is not the EMPIAR-13192 entry")
    if entry.get("title") != ENTRY_TITLE or entry.get("entry_doi") != ENTRY_DOI:
        raise SourceError("EMPIAR entry title or DOI changed")
    if entry.get("status") != "REL" or entry.get("experiment_type") != "SBF-SEM":
        raise SourceError("EMPIAR entry is not a released SBF-SEM entry")
    sets = [item for item in entry.get("imagesets", []) if item.get("directory") == IMAGESET_DIR]
    if len(sets) != 1:
        raise SourceError("Carotid2 imageset missing or ambiguous")
    item = sets[0]
    expected = {
        "num_images_or_tilt_series": VOLUME_SLICES,
        "frames_per_image": 1,
        "voxel_type": "UNSIGNED BYTE",
        "data_format": "TIFF",
        "image_width": str(WIDTH),
        "image_height": str(HEIGHT),
        "pixel_width": 650.0,
        "pixel_height": 650.0,
    }
    for key, value in expected.items():
        if item.get(key) != value:
            raise SourceError(f"Carotid2 imageset field {key} changed: {item.get(key)!r}")
    return {"imageset_name": item.get("name"), "details": item.get("details"), "release_date": entry.get("release_date")}


def check_listing(path: Path) -> int:
    """The Carotid2 directory holds only sequential slice TIFFs and every selected one.

    The ftp.ebi.ac.uk HTTPS front end is load-balanced and one backend's
    autoindex omitted Carotid2_Z1236.tif on 2026-10-06 (the file itself still
    answered 206), so the listing may show 1249 or 1250 names; the EMPIAR API
    count (1250) is authoritative.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    names = set(re.findall(r'href="([^"?/]+\.tif)"', text))
    allowed = {file_name(z) for z in range(1, VOLUME_SLICES + 1)}
    if names - allowed:
        raise SourceError(f"unexpected TIFFs in Carotid2 listing: {sorted(names - allowed)[:5]}")
    missing = [z for z in SELECTED_Z if file_name(z) not in names]
    if missing or len(names) < VOLUME_SLICES - 1:
        raise SourceError(f"Carotid2 listing has {len(names)} TIFFs; missing selected slices {missing}")
    return len(names)


def check_license(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)
    if LICENSE_SENTENCE not in text:
        raise SourceError("EMPIAR FAQ no longer states the CC0 licence sentence")


# ------------------------------------------------------------------ TIFF layout


def parse_fei_text(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in text.replace("\r", "").split("\n"):
        match = re.fullmatch(r"\[(.+)\]", line.strip())
        if match:
            current = sections.setdefault(match.group(1), {})
            continue
        if current is not None and "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = value.strip()
    return sections


def parse_layout(read_at: ReadAt, total_size: int) -> dict[str, object]:
    """Validate the FEI single-IFD layout; return metadata. Raises SourceError."""
    if total_size <= IFD_OFFSET + 2:
        raise SourceError(f"file too small: {total_size}")
    if read_at(0, 8) != HEADER:
        raise SourceError("not a little-endian classic TIFF with the IFD after the pixel block")
    (count,) = struct.unpack("<H", read_at(IFD_OFFSET, 2))
    if count != len(EXPECTED_TAGS):
        raise SourceError(f"unexpected IFD entry count {count}")
    table = read_at(IFD_OFFSET + 2, count * 12 + 4)
    ifd_end = IFD_OFFSET + 2 + count * 12 + 4
    (next_ifd,) = struct.unpack_from("<I", table, count * 12)
    if next_ifd != 0:
        raise SourceError("more than one IFD")
    entries: dict[int, tuple[int, int, bytes]] = {}
    blocks: list[tuple[int, int]] = []
    previous = -1
    for index in range(count):
        tag, typ, n, value = struct.unpack_from("<HHII", table, index * 12)
        if tag <= previous or typ not in TYPE_SIZES:
            raise SourceError(f"IFD entries unsorted or unknown type at tag {tag}")
        previous = tag
        size = TYPE_SIZES[typ] * n
        if size <= 4:
            raw = table[index * 12 + 8 : index * 12 + 8 + size]
        else:
            if value < ifd_end or value + size > total_size:
                raise SourceError(f"tag {tag} data outside the metadata tail")
            raw = read_at(value, size)
            blocks.append((value, value + size))
        entries[tag] = (typ, n, raw)
    if tuple(entries) != EXPECTED_TAGS:
        raise SourceError(f"unexpected tag set {tuple(entries)}")
    # Out-of-line payloads must tile [ifd_end, EOF) exactly, allowing only a
    # single zero word-alignment byte after an odd-length payload.
    blocks.sort()
    cursor = ifd_end
    for start, end in blocks + [(total_size, total_size)]:
        gap = start - cursor
        if gap < 0:
            raise SourceError("overlapping out-of-line tag data")
        if gap > 1 or (gap == 1 and (cursor % 2 == 0 or read_at(cursor, 1) != b"\x00")):
            raise SourceError(f"unexplained {gap} bytes at offset {cursor} in the metadata tail")
        cursor = end

    def scalar(tag: int) -> int:
        typ, n, raw = entries[tag]
        if n != 1 or typ not in (3, 4):
            raise SourceError(f"tag {tag} is not a SHORT/LONG scalar")
        return struct.unpack("<" + TYPE_FORMATS[typ], raw)[0]

    expected_scalars = {254: 0, 256: WIDTH, 257: HEIGHT, 258: 8, 259: 1, 262: 1, 277: 1, 278: ROWS_PER_STRIP}
    for tag, wanted in expected_scalars.items():
        if scalar(tag) != wanted:
            raise SourceError(f"tag {tag} = {scalar(tag)}, expected {wanted}")
    for tag in (273, 279):
        typ, n, _raw = entries[tag]
        if typ != 4 or n != STRIP_COUNT:
            raise SourceError(f"tag {tag} is not {STRIP_COUNT} LONG values")
    offsets = struct.unpack(f"<{STRIP_COUNT}I", entries[273][2])
    counts = struct.unpack(f"<{STRIP_COUNT}I", entries[279][2])
    if any(c != STRIP_BYTES for c in counts) or sum(counts) != PIXEL_BYTES:
        raise SourceError("strip byte counts are not 2048 x 12288")
    if any(o != 8 + i * STRIP_BYTES for i, o in enumerate(offsets)):
        raise SourceError("strips are not contiguous from byte 8")
    resolution_unit = scalar(296)
    x_res = struct.unpack("<II", entries[282][2])
    y_res = struct.unpack("<II", entries[283][2])
    for tag in (34682, 34683):
        if entries[tag][0] != 2:
            raise SourceError(f"FEI tag {tag} is not ASCII")
    fei_text = entries[34682][2].rstrip(b"\x00").decode("latin-1")
    fei_xml = entries[34683][2].rstrip(b"\x00").decode("latin-1")
    fei = parse_fei_text(fei_text)
    for (section, key), wanted in FEI_REQUIRED.items():
        got = fei.get(section, {}).get(key)
        if got != wanted:
            raise SourceError(f"FEI [{section}] {key} = {got!r}, expected {wanted!r}")
    compact_xml = re.sub(r">\s+<", "><", fei_xml)
    for fragment in XML_REQUIRED:
        if fragment not in compact_xml:
            raise SourceError(f"FEI XML lacks {fragment.split('>')[0]}> invariant")
    match = re.search(r"<AcquisitionDatetime>([0-9T:\-]+)</AcquisitionDatetime>", fei_xml)
    if not match:
        raise SourceError("FEI XML lacks AcquisitionDatetime")
    return {
        "acquisition_datetime": match.group(1),
        "resolution_unit": resolution_unit,
        "x_resolution": list(x_res),
        "y_resolution": list(y_res),
        "fei": {
            "dwell_time_s": fei.get("Scan", {}).get("Dwelltime"),
            "frame_time_s": fei.get("Scan", {}).get("FrameTime"),
            "beam_current_a": fei.get("EBeam", {}).get("BeamCurrent"),
            "working_distance_m": fei.get("EBeam", {}).get("WD"),
            "detector_contrast": fei.get("VS DBS", {}).get("Contrast"),
            "detector_brightness": fei.get("VS DBS", {}).get("Brightness"),
            "digital_contrast": fei.get("Image", {}).get("DigitalContrast"),
            "chamber_pressure_pa": fei.get("Vacuum", {}).get("ChPressure"),
        },
    }


def file_reader(handle) -> ReadAt:
    def read_at(offset: int, length: int) -> bytes:
        handle.seek(offset)
        data = handle.read(length)
        if len(data) != length:
            raise SourceError(f"short read at {offset}")
        return data

    return read_at


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def metadata_sha256(read_at: ReadAt, total_size: int) -> str:
    return hashlib.sha256(read_at(IFD_OFFSET, total_size - IFD_OFFSET)).hexdigest()


def validate_source(path: Path, z: int, pin: dict[str, str], require_file_hash: bool = True) -> dict[str, object]:
    if not path.is_file():
        raise SourceError(f"missing source file {path.name}")
    total = path.stat().st_size
    if total != int(pin["size_bytes"]):
        raise SourceError(f"{path.name}: size {total} != pinned {pin['size_bytes']}")
    with path.open("rb") as handle:
        read_at = file_reader(handle)
        layout = parse_layout(read_at, total)
        meta_hash = metadata_sha256(read_at, total)
    if meta_hash != pin["metadata_sha256"]:
        raise SourceError(f"{path.name}: metadata tail SHA-256 changed")
    if layout["acquisition_datetime"] != pin["acquisition_datetime"]:
        raise SourceError(f"{path.name}: acquisition timestamp changed")
    file_hash = sha256_file(path)
    if pin["file_sha256"] and file_hash != pin["file_sha256"]:
        raise SourceError(f"{path.name}: whole-file SHA-256 changed")
    if require_file_hash and not pin["file_sha256"]:
        raise SourceError(f"{path.name}: whole-file SHA-256 is not pinned yet")
    layout.update({"z": z, "source_size_bytes": total, "metadata_sha256": meta_hash, "file_sha256": file_hash})
    return layout


def read_pixels(path: Path) -> bytes:
    with path.open("rb") as handle:
        handle.seek(8)
        block = handle.read(PIXEL_BYTES)
    if len(block) != PIXEL_BYTES:
        raise SourceError(f"{path.name}: short pixel block")
    return block


# ------------------------------------------------------------------ pixel stats


def pixel_stats(block: bytes) -> dict[str, object]:
    if len(block) != PIXEL_BYTES:
        raise SourceError("pixel block has the wrong size")
    hist = collections.Counter(block)
    total = len(block)
    values = sorted(hist)
    modal_value, modal_count = max(hist.items(), key=lambda item: (item[1], -item[0]))
    constant_rows = 0
    for row in range(HEIGHT):
        line = block[row * WIDTH : (row + 1) * WIDTH]
        if line.count(line[:1]) == WIDTH:
            constant_rows += 1
    constant_cols = 0
    for col in range(WIDTH):
        column = block[col::WIDTH]
        if column.count(column[:1]) == HEIGHT:
            constant_cols += 1
    edges = {
        "top_row": len(set(block[:WIDTH])),
        "bottom_row": len(set(block[(HEIGHT - 1) * WIDTH :])),
        "left_col": len(set(block[0::WIDTH])),
        "right_col": len(set(block[WIDTH - 1 :: WIDTH])),
    }
    stats = {
        "minimum": values[0],
        "maximum": values[-1],
        "distinct_values": len(values),
        "mean": round(sum(v * c for v, c in hist.items()) / total, 6),
        "zero_values": hist.get(0, 0),
        "max_values": hist.get(255, 0),
        "modal_value": modal_value,
        "modal_fraction": round(modal_count / total, 9),
        "constant_rows": constant_rows,
        "constant_cols": constant_cols,
        "edge_distinct_values": edges,
        "zlib1_ratio": round(len(zlib.compress(block, 1)) / total, 6),
        "sha256": hashlib.sha256(block).hexdigest(),
    }
    problems = []
    if stats["minimum"] == stats["maximum"]:
        problems.append("constant frame")
    if stats["distinct_values"] < MIN_DISTINCT:
        problems.append(f"only {stats['distinct_values']} distinct values")
    if stats["modal_fraction"] > MAX_MODAL_FRACTION:
        problems.append(f"modal value {modal_value} covers {stats['modal_fraction']:.3f} of pixels")
    if constant_rows or constant_cols:
        problems.append(f"{constant_rows} constant rows / {constant_cols} constant columns (padding?)")
    if problems:
        raise SourceError("degenerate frame: " + "; ".join(problems))
    return stats


# ------------------------------------------------------------------ build / verify


def output_name(z: int) -> str:
    return f"carotid2_z{z:04d}_h{HEIGHT}_w{WIDTH}_u8.bin"


def scan_all(download_dir: Path, require_file_hash: bool) -> list[dict[str, object]]:
    pins = load_pins()
    check_entry(download_dir / "empiar_13192_entry.json")
    check_license(download_dir / "empiar_faq.html")
    reports = []
    seen: set[str] = set()
    for z in SELECTED_Z:
        source = download_dir / file_name(z)
        layout = validate_source(source, z, pins[z], require_file_hash)
        block = read_pixels(source)
        try:
            stats = pixel_stats(block)
        except SourceError as error:
            raise SourceError(f"{source.name}: {error}") from error
        if stats["sha256"] in seen:
            raise SourceError(f"{source.name}: duplicate pixel payload")
        seen.add(str(stats["sha256"]))
        reports.append({**layout, **stats})
        print(
            f"z={z:04d} acq={layout['acquisition_datetime']} min={stats['minimum']} max={stats['maximum']} "
            f"distinct={stats['distinct_values']} mean={stats['mean']:.2f} zeros={stats['zero_values']} "
            f"modal={stats['modal_fraction']:.4f} zlib1={stats['zlib1_ratio']}",
            flush=True,
        )
    return reports


def summarize(reports: list[dict[str, object]]) -> dict[str, object]:
    summary = _summarize(reports)
    if summary["output_digest"] != EXPECTED_OUTPUT_DIGEST:
        raise SourceError(f"output digest {summary['output_digest']} != pinned {EXPECTED_OUTPUT_DIGEST}")
    return summary


def _summarize(reports: list[dict[str, object]]) -> dict[str, object]:
    ratios = [float(r["zlib1_ratio"]) for r in reports]
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(reports),
        "value_count": len(reports) * PIXEL_BYTES,
        "total_size_bytes": len(reports) * PIXEL_BYTES,
        "selected_z": list(SELECTED_Z),
        "unique_payloads": len({r["sha256"] for r in reports}),
        "global_minimum": min(int(r["minimum"]) for r in reports),
        "global_maximum": max(int(r["maximum"]) for r in reports),
        "minimum_distinct_values": min(int(r["distinct_values"]) for r in reports),
        "zero_values": sum(int(r["zero_values"]) for r in reports),
        "max_values": sum(int(r["max_values"]) for r in reports),
        "maximum_modal_fraction": max(float(r["modal_fraction"]) for r in reports),
        "constant_rows": sum(int(r["constant_rows"]) for r in reports),
        "constant_cols": sum(int(r["constant_cols"]) for r in reports),
        "minimum_zlib1_ratio": min(ratios),
        "median_zlib1_ratio": statistics.median(ratios),
        "maximum_zlib1_ratio": max(ratios),
        "first_acquisition": min(str(r["acquisition_datetime"]) for r in reports),
        "last_acquisition": max(str(r["acquisition_datetime"]) for r in reports),
        "output_digest": hashlib.sha256(
            "".join(f"{output_name(int(r['z']))}\t{r['sha256']}\n" for r in reports).encode()
        ).hexdigest(),
    }


def index_row(report: dict[str, object], sample_path: str) -> dict[str, object]:
    z = int(report["z"])
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_path,
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": PIXEL_BYTES,
        "value_count": PIXEL_BYTES,
        "sample_format": "raw homogeneous uint8 SBF-SEM backscatter block-face image",
        "sample_geometry": "sbfsem_block_face_scan_raster_2d",
        "sample_rank": 2,
        "sample_shape": [HEIGHT, WIDTH],
        "sample_axes": ["scan_line_y", "scan_pixel_x"],
        "natural_record_kind": "sbfsem_block_face_slice_tiff",
        "source_url": f"{BASE_URL}/{file_name(z)}",
        "source_file": file_name(z),
        "source_size_bytes": report["source_size_bytes"],
        "source_file_sha256": report["file_sha256"],
        "source_pixel_offset": 8,
        "z_index": z,
        "z_depth_um": round((z - 1) * 0.2, 1),
        "acquisition_datetime": report["acquisition_datetime"],
        "pixel_size_nm": 65,
        "minimum": report["minimum"],
        "maximum": report["maximum"],
        "distinct_values": report["distinct_values"],
        "mean": report["mean"],
        "sha256": report["sha256"],
    }


def build(args: argparse.Namespace) -> None:
    reports = scan_all(args.download_dir, require_file_hash=not args.allow_unpinned)
    summary = summarize(reports)
    series_dir = args.data_root / "samples" / DATASET_ID / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for report in reports:
        z = int(report["z"])
        output = series_dir / output_name(z)
        block = read_pixels(args.download_dir / file_name(z))
        if hashlib.sha256(block).hexdigest() != report["sha256"]:
            raise SourceError(f"source changed during build: z={z}")
        output.write_bytes(block)
        rows.append(index_row(report, output.relative_to(args.data_root).as_posix()))
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats_path = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps({**summary, "frames": reports}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    # Independent re-derivation from the downloaded TIFFs.
    reports = scan_all(args.download_dir, require_file_hash=not args.allow_unpinned)
    summary = summarize(reports)
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index_path.is_file() or not stats_path.is_file():
        raise SourceError("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(SELECTED_Z):
        raise SourceError(f"index has {len(rows)} rows, expected {len(SELECTED_Z)}")
    expected_paths = set()
    for row, report in zip(rows, reports, strict=True):
        z = int(report["z"])
        expected_row = json.loads(json.dumps(index_row(report, f"samples/{DATASET_ID}/{SERIES_ID}/{output_name(z)}")))
        if row != expected_row:
            diff = sorted(k for k in set(row) | set(expected_row) if row.get(k) != expected_row.get(k))
            raise SourceError(f"index row mismatch for z={z}: {diff}")
        output = args.data_root / row["sample_path"]
        expected_paths.add(output.resolve())
        if not output.is_file() or output.stat().st_size != PIXEL_BYTES:
            raise SourceError(f"missing or mis-sized sample for z={z}")
        data = output.read_bytes()
        if data != read_pixels(args.download_dir / file_name(z)):
            raise SourceError(f"sample for z={z} is not the source pixel block")
        if pixel_stats(data) != {k: report[k] for k in pixel_stats_keys()}:
            raise SourceError(f"sample statistics differ for z={z}")
    actual = {p.resolve() for p in (args.data_root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if actual != expected_paths:
        raise SourceError("sample directory contents do not match the index")
    stored = json.loads(stats_path.read_text(encoding="utf-8"))
    for key, value in summary.items():
        if stored.get(key) != value:
            raise SourceError(f"ingest statistic {key} differs: {stored.get(key)!r} != {value!r}")
    if stored.get("frames") != json.loads(json.dumps(reports)):
        raise SourceError("stored per-frame reports differ")
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or len(manifest["series"]) != 1:
        raise SourceError("manifest must declare exactly the one primary series")
    if int(series[0]["sample_count"]) != summary["sample_count"] or int(series[0]["total_size_bytes"]) != summary["total_size_bytes"]:
        raise SourceError("manifest sample_count/total_size_bytes do not match realized output")
    if summary["unique_payloads"] != len(SELECTED_Z) or summary["constant_rows"] or summary["constant_cols"]:
        raise SourceError("aggregate degeneracy check failed")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": summary["sample_count"],
        "verified_values": summary["value_count"],
        "verified_bytes": summary["total_size_bytes"],
        "output_digest": summary["output_digest"],
    }, indent=2, sort_keys=True))


def pixel_stats_keys() -> list[str]:
    return [
        "minimum", "maximum", "distinct_values", "mean", "zero_values", "max_values", "modal_value",
        "modal_fraction", "constant_rows", "constant_cols", "edge_distinct_values", "zlib1_ratio", "sha256",
    ]


# ------------------------------------------------------------------ download helpers


def cmd_check_file(args: argparse.Namespace) -> None:
    pins = load_pins()
    z = args.z
    if z not in pins:
        raise SourceError(f"z={z} is not a selected slice")
    layout = validate_source(args.path, z, pins[z], require_file_hash=False)
    block = read_pixels(args.path)
    if block.count(block[:1]) == len(block):
        raise SourceError(f"{args.path.name}: constant pixel block")
    print(f"ok {file_name(z)} size={layout['source_size_bytes']} acq={layout['acquisition_datetime']} sha256={layout['file_sha256']}")


def cmd_inventory(args: argparse.Namespace) -> None:
    pins = load_pins()
    entry = check_entry(args.download_dir / "empiar_13192_entry.json")
    check_license(args.download_dir / "empiar_faq.html")
    files = []
    for z in SELECTED_Z:
        layout = validate_source(args.download_dir / file_name(z), z, pins[z], require_file_hash=False)
        files.append({k: layout[k] for k in ("z", "source_size_bytes", "metadata_sha256", "file_sha256", "acquisition_datetime")})
    inventory = {
        "entry": ENTRY_KEY,
        "doi": ENTRY_DOI,
        "imageset": entry,
        "license": "CC0-1.0",
        "selected_z": list(SELECTED_Z),
        "files": files,
        "download_bytes": sum(int(f["source_size_bytes"]) for f in files),
        "unpinned_file_sha256": [f["z"] for f in files if not pins[int(f["z"])]["file_sha256"]],
    }
    (args.download_dir / "source_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"inventory files={len(files)} bytes={inventory['download_bytes']} unpinned={len(inventory['unpinned_file_sha256'])}")


def cmd_pins(args: argparse.Namespace) -> None:
    """Print z, file name, URL and pinned size for download.sh."""
    pins = load_pins()
    for z in SELECTED_Z:
        print(f"{z}\t{file_name(z)}\t{BASE_URL}/{file_name(z)}\t{pins[z]['size_bytes']}")


def cmd_probe_row(args: argparse.Namespace) -> None:
    """Discovery helper: build a pin row from a header range and a metadata-tail range."""
    head = args.head.read_bytes()
    tail = args.tail.read_bytes()
    total = args.size
    if len(head) != 8 or IFD_OFFSET + len(tail) != total:
        raise SourceError(f"z={args.z}: probe ranges do not match Content-Length {total}")

    def read_at(offset: int, length: int) -> bytes:
        if offset + length <= 8:
            return head[offset : offset + length]
        if offset >= IFD_OFFSET and offset + length <= total:
            return tail[offset - IFD_OFFSET : offset - IFD_OFFSET + length]
        raise SourceError(f"probe read outside fetched ranges at {offset}")

    layout = parse_layout(read_at, total)
    print("\t".join([
        str(args.z), file_name(args.z), str(total), hashlib.sha256(tail).hexdigest(),
        str(layout["acquisition_datetime"]), "-",
    ]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-entry"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-license"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-file"); p.add_argument("path", type=Path); p.add_argument("z", type=int)
    p = sub.add_parser("inventory"); p.add_argument("--download-dir", type=Path, required=True)
    sub.add_parser("pins")
    sub.add_parser("selected")
    p = sub.add_parser("check-listing"); p.add_argument("path", type=Path)
    p = sub.add_parser("probe-row")
    p.add_argument("--z", type=int, required=True)
    p.add_argument("--size", type=int, required=True)
    p.add_argument("--head", type=Path, required=True)
    p.add_argument("--tail", type=Path, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--allow-unpinned", action="store_true",
                       help="accept slices whose whole-file SHA-256 is not yet pinned (first run only)")
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "check-entry":
            print(json.dumps(check_entry(args.path)))
        elif args.command == "check-license":
            check_license(args.path)
            print("license ok: CC0")
        elif args.command == "check-file":
            cmd_check_file(args)
        elif args.command == "inventory":
            cmd_inventory(args)
        elif args.command == "pins":
            cmd_pins(args)
        elif args.command == "selected":
            print(" ".join(str(z) for z in SELECTED_Z))
        elif args.command == "check-listing":
            count = check_listing(args.path)
            print(f"listing ok: {count} slice TIFFs listed, all {len(SELECTED_Z)} selected slices present")
        elif args.command == "probe-row":
            cmd_probe_row(args)
        elif args.command == "build":
            build(args)
        else:
            verify(args)
    except SourceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
