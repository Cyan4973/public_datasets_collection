#!/usr/bin/env python3
"""EMPIAR-10511 Gatan K2 counting-mode movie frames: validate, build, verify.

Pure standard library. Each deposited movie is an MRC file written by Gatan
DigitalMicrograph (GMS 3.23): a 1024-byte header with no extended header
(NSYMBT = 0), then 40 contiguous 3838x3710 mode-0 (8-bit) sections, one per
dose-fractionated frame, each stored x-fastest. Only the header and one fixed
section (z = 20) per selected movie are fetched by byte range; the frame bytes
are the detector's per-pixel electron counts and are emitted unchanged.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import shutil
import statistics
import struct
import sys
import tomllib
import zlib
from pathlib import Path


DATASET_ID = "empiar_10511_k2_counting_movie_frames_u8"
SERIES_ID = "k2_counting_frame_u8"
ENTRY_KEY = "EMPIAR-10511"
ENTRY_TITLE = "mouse cGAS with nucleosomes from 293T"
ENTRY_DOI = "10.6019/EMPIAR-10511"
BASE_URL = "https://ftp.ebi.ac.uk/empiar/world_availability/10511/data"
LICENSE_SENTENCE = (
    "All data in EMPIAR is freely and publicly available to the global community under the CC0 license"
)

NX = 3838  # MRC columns (fastest axis)
NY = 3710  # MRC rows
NZ = 40  # frames per movie
HEADER_BYTES = 1024
FRAME_BYTES = NX * NY  # 14,238,980
FILE_SIZE = HEADER_BYTES + NZ * FRAME_BYTES  # 569,560,224
FRAME_INDEX = 20  # 0-based section index: the 21st of 40 frames
FRAME_START = HEADER_BYTES + FRAME_INDEX * FRAME_BYTES  # 284,780,624
FRAME_END = FRAME_START + FRAME_BYTES - 1  # 299,019,603 (inclusive)
PROBE_BYTES = 65536  # frame prefix fingerprinted at discovery time
MOVIE_COUNT = 2979
SELECTED_COUNT = 40
GAIN_REFERENCE = "gain-reference.mrc"
GMS_LABEL = b"Digital Micrograph(TM), GMS v 3.23"
MOVIE_RE = re.compile(r"FoilHole_(\d+)_Data_(\d+)_(\d+)_(\d{8})_(\d{6})-(\d+)\.mrc")
PINS_PATH = Path(__file__).with_name("k2_movies.tsv")
PIN_FIELDS = ["slot", "listing_index", "file_name", "size_bytes", "header_sha256", "frame_prefix_sha256", "frame_sha256"]

# Degeneracy guards, applied identically by download, build and verify, except
# MAX_SIGNED_SAFE, which build and verify enforce (download only reports it).
# GMS fills the header DMIN/DMAX/DMEAN from the FIRST frame, not the whole stack
# (probe 2026-10-06: movie slot 0 has DMAX 44 = max of frame 0, while frame 20
# reaches 64; DMEAN 0.8641 vs frame-0 mean 0.8627), so frames are compared with
# the header mean only, never with DMIN/DMAX.
MAX_SIGNED_SAFE = 127  # mode 0 is int8 in MRC2014; EMPIAR declares UNSIGNED BYTE; both agree below 128
MIN_DISTINCT = 8
MEAN_RANGE = (0.5, 1.5)  # electrons per pixel per frame
MAX_MEAN_DEVIATION = 0.25  # relative to the header DMEAN (first-frame mean; dose rate is constant)
HOT_VALUE = 16  # values at or above this are counted (isolated hot/bright pixels), not rejected
MAX_MODAL_FRACTION = 0.75
MAX_CONSTANT_LINES = 37  # about 1 % of rows or columns; more suggests padding or masking

# SHA-256 over "<sample name>\t<sample sha256>\n" lines in slot order, pinned
# from the first verified build; empty until then.
EXPECTED_OUTPUT_DIGEST = "1f736f4887d93b62c74579e725e7b50a3c9c3f30ab03a433d73d83787e353926"


class SourceError(Exception):
    pass


# ------------------------------------------------------------------ selection / pins


def selected_indices() -> list[int]:
    """Bin centres of 40 equal bins over the 2979 name-sorted movies."""
    return [((2 * slot + 1) * MOVIE_COUNT) // (2 * SELECTED_COUNT) for slot in range(SELECTED_COUNT)]


def movie_url(name: str) -> str:
    return f"{BASE_URL}/{name}"


def header_name(name: str) -> str:
    return f"headers/{name}.hdr"


def frame_name(name: str) -> str:
    return f"frames/{name}.z{FRAME_INDEX:02d}"


def output_name(slot: int, name: str) -> str:
    return f"k2_{slot:02d}_{name[:-4]}_z{FRAME_INDEX:02d}_h{NY}_w{NX}_u8.bin"


def load_pins() -> list[dict[str, str]]:
    with PINS_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or list(rows[0].keys()) != PIN_FIELDS:
        raise SourceError(f"unexpected pin columns in {PINS_PATH.name}")
    if len(rows) != SELECTED_COUNT:
        raise SourceError(f"pin table has {len(rows)} rows, expected {SELECTED_COUNT}")
    indices = selected_indices()
    previous = ""
    for slot, row in enumerate(rows):
        row["frame_sha256"] = "" if row["frame_sha256"] == "-" else row["frame_sha256"]
        if int(row["slot"]) != slot or int(row["listing_index"]) != indices[slot]:
            raise SourceError(f"pin row {slot} has the wrong slot or listing index")
        if not MOVIE_RE.fullmatch(row["file_name"]) or row["file_name"] <= previous:
            raise SourceError(f"pin row {slot}: file name malformed or not in name order")
        previous = row["file_name"]
        if int(row["size_bytes"]) != FILE_SIZE:
            raise SourceError(f"pin row {slot}: size {row['size_bytes']} != {FILE_SIZE}")
        for key in ("header_sha256", "frame_prefix_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                raise SourceError(f"pin row {slot}: malformed {key}")
        if row["frame_sha256"] and not re.fullmatch(r"[0-9a-f]{64}", row["frame_sha256"]):
            raise SourceError(f"pin row {slot}: malformed frame_sha256")
    return rows


def name_fields(name: str) -> dict[str, object]:
    match = MOVIE_RE.fullmatch(name)
    if not match:
        raise SourceError(f"unexpected movie name {name}")
    hole, area, area2, day, clock, serial = match.groups()
    return {
        "foil_hole_id": int(hole),
        "acquisition_template_id": int(area),
        "acquisition_datetime": f"{day[:4]}-{day[4:6]}-{day[6:]}T{clock[:2]}:{clock[2:4]}:{clock[4:]}",
        "epu_serial": int(serial),
    }


# ------------------------------------------------------------------ entry / licence / listing


def check_entry(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data.get(ENTRY_KEY)
    if not isinstance(entry, dict):
        raise SourceError("EMPIAR API response is not the EMPIAR-10511 entry")
    if entry.get("title") != ENTRY_TITLE or entry.get("entry_doi") != ENTRY_DOI:
        raise SourceError("EMPIAR entry title or DOI changed")
    if entry.get("status") != "REL":
        raise SourceError("EMPIAR entry is not released")
    sets = entry.get("imagesets", [])
    if len(sets) != 1 or sets[0].get("directory") != "data":
        raise SourceError("EMPIAR-10511 no longer has exactly one imageset in data/")
    item = sets[0]
    expected = {
        "category": "micrographs - multiframe",
        "header_format": "MRC",
        "data_format": "MRC",
        "num_images_or_tilt_series": MOVIE_COUNT,
        "frames_per_image": NZ,
        "voxel_type": "UNSIGNED BYTE",
        "image_width": str(NX),
        "image_height": str(NY),
        "pixel_width": 1.07,
        "pixel_height": 1.07,
    }
    for key, value in expected.items():
        if item.get(key) != value:
            raise SourceError(f"imageset field {key} changed: {item.get(key)!r}")
    return {
        "imageset_name": item.get("name"),
        "release_date": entry.get("release_date"),
        "cross_references": entry.get("cross_references"),
        "related_pdb_entries": entry.get("related_pdb_entries"),
    }


def check_license(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    if LICENSE_SENTENCE not in text:
        raise SourceError("EMPIAR FAQ no longer states the CC0 licence sentence")


def check_listing(path: Path) -> list[str]:
    """data/ must hold exactly the 2979 movies (listed 543M) plus the 54M gain reference."""
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = re.findall(r'<a href="([^"?/]+)">[^<]*</a></td><td[^>]*>[^<]*</td><td[^>]*>\s*([^<]*?)\s*</td>', text)
    sizes = dict(rows)
    if len(sizes) != len(rows):
        raise SourceError("duplicate names in the data/ listing")
    if sizes.pop(GAIN_REFERENCE, None) != "54M":
        raise SourceError("gain-reference.mrc missing or resized in listing")
    movies = sorted(sizes)
    bad = [name for name in movies if not MOVIE_RE.fullmatch(name) or sizes[name] != "543M"]
    if bad:
        raise SourceError(f"unexpected entries in data/ listing: {bad[:5]}")
    if len(movies) != MOVIE_COUNT:
        raise SourceError(f"listing has {len(movies)} movies, expected {MOVIE_COUNT}")
    return movies


# ------------------------------------------------------------------ MRC header


def parse_header(raw: bytes) -> dict[str, object]:
    """Validate the GMS-written MRC header of one movie. Raises SourceError."""
    if len(raw) != HEADER_BYTES:
        raise SourceError(f"header has {len(raw)} bytes, expected {HEADER_BYTES}")
    nx, ny, nz, mode = struct.unpack_from("<4i", raw, 0)
    if (nx, ny, nz, mode) != (NX, NY, NZ, 0):
        raise SourceError(f"nx/ny/nz/mode = {nx}/{ny}/{nz}/{mode}, expected {NX}/{NY}/{NZ}/0")
    if struct.unpack_from("<3i", raw, 16) != (0, 0, 0):
        raise SourceError("nonzero NXSTART/NYSTART/NZSTART")
    if struct.unpack_from("<3i", raw, 28) != (NX, NY, NZ):
        raise SourceError("MX/MY/MZ differ from the frame geometry")
    if struct.unpack_from("<3i", raw, 64) != (1, 2, 3):
        raise SourceError("MAPC/MAPR/MAPS is not 1/2/3 (x fastest)")
    dmin, dmax, dmean = struct.unpack_from("<3f", raw, 76)
    ispg, nsymbt = struct.unpack_from("<2i", raw, 88)
    if ispg != 0 or nsymbt != 0:
        raise SourceError(f"ISPG/NSYMBT = {ispg}/{nsymbt}; frames would not start at byte 1024")
    if any(raw[96:196]):
        raise SourceError("EXTRA/EXTTYP/NVERSION/IMOD fields are not zero")
    if raw[208:212] != b"MAP " or raw[212:214] != b"\x44\x41":
        raise SourceError("missing 'MAP ' tag or little-endian machine stamp")
    (nlabl,) = struct.unpack_from("<i", raw, 220)
    label = raw[224:304]
    if nlabl != 1 or not label.startswith(GMS_LABEL) or any(label[len(GMS_LABEL):]) or any(raw[304:1024]):
        raise SourceError("labels are not the single GMS 3.23 label")
    if dmin != 0.0 or not (dmax == int(dmax) and 8 <= dmax <= MAX_SIGNED_SAFE):
        raise SourceError(f"header (first-frame) DMIN/DMAX {dmin}/{dmax} outside the counting-mode range")
    if not (MEAN_RANGE[0] <= dmean <= MEAN_RANGE[1]):
        raise SourceError(f"header DMEAN {dmean} outside {MEAN_RANGE}")
    return {
        "header_dmin": dmin,
        "header_dmax": dmax,
        "header_dmean": round(dmean, 7),
        "header_rms": struct.unpack_from("<f", raw, 216)[0],
        "header_cella": list(struct.unpack_from("<3f", raw, 40)),
    }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ frame statistics


def frame_stats(block: bytes, header: dict[str, object], int8_safe: bool = True) -> dict[str, object]:
    if len(block) != FRAME_BYTES:
        raise SourceError(f"frame has {len(block)} bytes, expected {FRAME_BYTES}")
    low, high = min(block), max(block)
    hist = {v: block.count(bytes((v,))) for v in range(low, high + 1)}
    hist = {v: c for v, c in hist.items() if c}
    total = len(block)
    mean = sum(v * c for v, c in hist.items()) / total
    modal_value, modal_count = max(hist.items(), key=lambda item: (item[1], -item[0]))
    entropy = -sum(c / total * math.log2(c / total) for c in hist.values())
    constant_rows = 0
    row_sums = []
    for row in range(NY):
        line = block[row * NX : (row + 1) * NX]
        if line.count(line[:1]) == NX:
            constant_rows += 1
        row_sums.append(sum(line))
    constant_cols = 0
    for col in range(NX):
        column = block[col::NX]
        if column.count(column[:1]) == NY:
            constant_cols += 1
    stats = {
        "minimum": low,
        "maximum": high,
        "distinct_values": len(hist),
        "mean": round(mean, 6),
        "zero_fraction": round(hist.get(0, 0) / total, 6),
        "hot_values": sum(c for v, c in hist.items() if v >= HOT_VALUE),
        "modal_value": modal_value,
        "modal_fraction": round(modal_count / total, 6),
        "entropy_bits": round(entropy, 6),
        "histogram": {str(v): c for v, c in sorted(hist.items())},
        "constant_rows": constant_rows,
        "constant_cols": constant_cols,
        "min_row_mean": round(min(row_sums) / NX, 6),
        "max_row_mean": round(max(row_sums) / NX, 6),
        "zlib1_ratio": round(len(zlib.compress(block, 1)) / total, 6),
        "sha256": sha256_bytes(block),
    }
    problems = []
    if low == high:
        problems.append("constant frame")
    if int8_safe and high > MAX_SIGNED_SAFE:
        problems.append(f"maximum {high} >= 128 (int8/uint8 readings would disagree)")
    if len(hist) < MIN_DISTINCT:
        problems.append(f"only {len(hist)} distinct values")
    if not (MEAN_RANGE[0] <= mean <= MEAN_RANGE[1]):
        problems.append(f"mean {mean:.4f} e/pixel outside {MEAN_RANGE}")
    if abs(mean / float(header["header_dmean"]) - 1.0) > MAX_MEAN_DEVIATION:
        problems.append(f"mean {mean:.4f} deviates >25% from header DMEAN {header['header_dmean']}")
    if modal_count / total > MAX_MODAL_FRACTION:
        problems.append(f"modal value {modal_value} covers {modal_count / total:.3f} of pixels")
    if constant_rows > MAX_CONSTANT_LINES or constant_cols > MAX_CONSTANT_LINES:
        problems.append(f"{constant_rows} constant rows / {constant_cols} constant columns")
    if problems:
        raise SourceError("degenerate frame: " + "; ".join(problems))
    return stats


def stats_keys() -> list[str]:
    return [
        "minimum", "maximum", "distinct_values", "mean", "zero_fraction", "hot_values", "modal_value", "modal_fraction",
        "entropy_bits", "histogram", "constant_rows", "constant_cols", "min_row_mean", "max_row_mean",
        "zlib1_ratio", "sha256",
    ]


# ------------------------------------------------------------------ per-movie validation


def read_exact(path: Path, size: int) -> bytes:
    if not path.is_file():
        raise SourceError(f"missing local file {path.name}")
    data = path.read_bytes()
    if len(data) != size:
        raise SourceError(f"{path.name}: {len(data)} bytes, expected {size}")
    return data


def check_header_file(path: Path, pin: dict[str, str]) -> dict[str, object]:
    raw = read_exact(path, HEADER_BYTES)
    if sha256_bytes(raw) != pin["header_sha256"]:
        raise SourceError(f"{pin['file_name']}: header SHA-256 differs from pin")
    return parse_header(raw)


def check_frame_bytes(
    block: bytes, header: dict[str, object], pin: dict[str, str], require_hash: bool, int8_safe: bool = True
) -> dict[str, object]:
    if sha256_bytes(block[:PROBE_BYTES]) != pin["frame_prefix_sha256"]:
        raise SourceError(f"{pin['file_name']}: frame prefix SHA-256 differs from pin")
    digest = sha256_bytes(block)
    if pin["frame_sha256"] and digest != pin["frame_sha256"]:
        raise SourceError(f"{pin['file_name']}: frame SHA-256 differs from pin")
    if require_hash and not pin["frame_sha256"]:
        raise SourceError(f"{pin['file_name']}: frame SHA-256 is not pinned yet")
    try:
        return frame_stats(block, header, int8_safe)
    except SourceError as error:
        raise SourceError(f"{pin['file_name']}: {error}") from error


def scan_all(download_dir: Path, require_hash: bool, verbose: bool = True) -> list[dict[str, object]]:
    pins = load_pins()
    check_entry(download_dir / "empiar_10511_entry.json")
    check_license(download_dir / "empiar_faq.html")
    reports = []
    seen: set[str] = set()
    for pin in pins:
        name = pin["file_name"]
        header = check_header_file(download_dir / header_name(name), pin)
        block = read_exact(download_dir / frame_name(name), FRAME_BYTES)
        stats = check_frame_bytes(block, header, pin, require_hash)
        if stats["sha256"] in seen:
            raise SourceError(f"{name}: duplicate frame payload")
        seen.add(str(stats["sha256"]))
        report = {"slot": int(pin["slot"]), "listing_index": int(pin["listing_index"]), "file_name": name,
                  **name_fields(name), **header, **stats}
        reports.append(report)
        if verbose:
            print(
                f"slot={report['slot']:02d} {name} mean={stats['mean']:.4f} (hdr {header['header_dmean']:.4f}) "
                f"max={stats['maximum']} (frame-0 hdr {header['header_dmax']:.0f}) hot={stats['hot_values']} "
                f"distinct={stats['distinct_values']} "
                f"zero={stats['zero_fraction']:.4f} H={stats['entropy_bits']:.3f} const_rows={stats['constant_rows']} "
                f"const_cols={stats['constant_cols']} zlib1={stats['zlib1_ratio']}",
                flush=True,
            )
    return reports


def summarize(reports: list[dict[str, object]]) -> dict[str, object]:
    ratios = [float(r["zlib1_ratio"]) for r in reports]
    means = [float(r["mean"]) for r in reports]
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(reports),
        "value_count": len(reports) * FRAME_BYTES,
        "total_size_bytes": len(reports) * FRAME_BYTES,
        "frame_index": FRAME_INDEX,
        "selected_listing_indices": selected_indices(),
        "unique_payloads": len({r["sha256"] for r in reports}),
        "global_minimum": min(int(r["minimum"]) for r in reports),
        "global_maximum": max(int(r["maximum"]) for r in reports),
        "minimum_distinct_values": min(int(r["distinct_values"]) for r in reports),
        "minimum_mean": min(means),
        "median_mean": statistics.median(means),
        "maximum_mean": max(means),
        "median_entropy_bits": statistics.median(float(r["entropy_bits"]) for r in reports),
        "maximum_modal_fraction": max(float(r["modal_fraction"]) for r in reports),
        "constant_rows": sum(int(r["constant_rows"]) for r in reports),
        "constant_cols": sum(int(r["constant_cols"]) for r in reports),
        "minimum_zlib1_ratio": min(ratios),
        "median_zlib1_ratio": statistics.median(ratios),
        "maximum_zlib1_ratio": max(ratios),
        "first_acquisition": min(str(r["acquisition_datetime"]) for r in reports),
        "last_acquisition": max(str(r["acquisition_datetime"]) for r in reports),
        "output_digest": hashlib.sha256(
            "".join(f"{output_name(int(r['slot']), str(r['file_name']))}\t{r['sha256']}\n" for r in reports).encode()
        ).hexdigest(),
    }
    if EXPECTED_OUTPUT_DIGEST and summary["output_digest"] != EXPECTED_OUTPUT_DIGEST:
        raise SourceError(f"output digest {summary['output_digest']} != pinned {EXPECTED_OUTPUT_DIGEST}")
    return summary


def index_row(report: dict[str, object], sample_path: str) -> dict[str, object]:
    name = str(report["file_name"])
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_path,
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": FRAME_BYTES,
        "value_count": FRAME_BYTES,
        "sample_format": "raw homogeneous uint8 electron-counting detector frame",
        "sample_geometry": "detector_frame_raster_2d",
        "sample_rank": 2,
        "sample_shape": [NY, NX],
        "sample_axes": ["detector_row_y", "detector_column_x"],
        "natural_record_kind": "dose_fractionated_movie_frame",
        "source_url": movie_url(name),
        "source_file": name,
        "source_size_bytes": FILE_SIZE,
        "source_byte_range": [FRAME_START, FRAME_END],
        "frame_index": FRAME_INDEX,
        "frames_per_movie": NZ,
        "slot": report["slot"],
        "listing_index": report["listing_index"],
        "foil_hole_id": report["foil_hole_id"],
        "acquisition_template_id": report["acquisition_template_id"],
        "acquisition_datetime": report["acquisition_datetime"],
        "pixel_size_angstrom": 1.07,
        "header_dmax": report["header_dmax"],
        "header_dmean": report["header_dmean"],
        "minimum": report["minimum"],
        "maximum": report["maximum"],
        "mean": report["mean"],
        "distinct_values": report["distinct_values"],
        "entropy_bits": report["entropy_bits"],
        "sha256": report["sha256"],
    }


def build(args: argparse.Namespace) -> None:
    reports = scan_all(args.download_dir, require_hash=not args.allow_unpinned)
    summary = summarize(reports)
    series_dir = args.data_root / "samples" / DATASET_ID / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for report in reports:
        name = str(report["file_name"])
        block = read_exact(args.download_dir / frame_name(name), FRAME_BYTES)
        if sha256_bytes(block) != report["sha256"]:
            raise SourceError(f"source changed during build: {name}")
        output = series_dir / output_name(int(report["slot"]), name)
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
    # Independent re-derivation from the downloaded header and frame ranges.
    reports = scan_all(args.download_dir, require_hash=not args.allow_unpinned)
    summary = summarize(reports)
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index_path.is_file() or not stats_path.is_file():
        raise SourceError("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != SELECTED_COUNT:
        raise SourceError(f"index has {len(rows)} rows, expected {SELECTED_COUNT}")
    expected_paths = set()
    for row, report in zip(rows, reports, strict=True):
        name = str(report["file_name"])
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{output_name(int(report['slot']), name)}"
        expected_row = json.loads(json.dumps(index_row(report, rel)))
        if row != expected_row:
            diff = sorted(k for k in set(row) | set(expected_row) if row.get(k) != expected_row.get(k))
            raise SourceError(f"index row mismatch for {name}: {diff}")
        output = args.data_root / rel
        expected_paths.add(output.resolve())
        if not output.is_file() or output.stat().st_size != FRAME_BYTES:
            raise SourceError(f"missing or mis-sized sample for {name}")
        data = output.read_bytes()
        if data != read_exact(args.download_dir / frame_name(name), FRAME_BYTES):
            raise SourceError(f"sample for {name} is not the source frame")
        header = {k: report[k] for k in ("header_dmin", "header_dmax", "header_dmean")}
        if frame_stats(data, header) != {k: report[k] for k in stats_keys()}:
            raise SourceError(f"sample statistics differ for {name}")
    actual = {p.resolve() for p in (args.data_root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if actual != expected_paths:
        raise SourceError("sample directory contents do not match the index")
    stored = json.loads(stats_path.read_text(encoding="utf-8"))
    for key, value in summary.items():
        if stored.get(key) != json.loads(json.dumps(value)):
            raise SourceError(f"ingest statistic {key} differs: {stored.get(key)!r} != {value!r}")
    if stored.get("frames") != json.loads(json.dumps(reports)):
        raise SourceError("stored per-frame reports differ")
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = manifest.get("series", [])
    if len(series) != 1 or series[0].get("id") != SERIES_ID:
        raise SourceError("manifest must declare exactly the one primary series")
    if int(series[0]["sample_count"]) != summary["sample_count"] or int(series[0]["total_size_bytes"]) != summary["total_size_bytes"]:
        raise SourceError("manifest sample_count/total_size_bytes do not match realized output")
    if summary["unique_payloads"] != SELECTED_COUNT or summary["global_maximum"] > MAX_SIGNED_SAFE:
        raise SourceError("aggregate degeneracy check failed")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": summary["sample_count"],
        "verified_values": summary["value_count"],
        "verified_bytes": summary["total_size_bytes"],
        "global_range": [summary["global_minimum"], summary["global_maximum"]],
        "median_mean": summary["median_mean"],
        "output_digest": summary["output_digest"],
    }, indent=2, sort_keys=True))


# ------------------------------------------------------------------ download / discovery helpers


def cmd_pins(_args: argparse.Namespace) -> None:
    """slot, file name, URL, header path, frame path for download.sh."""
    for pin in load_pins():
        name = pin["file_name"]
        print(f"{pin['slot']}\t{name}\t{movie_url(name)}\t{header_name(name)}\t{frame_name(name)}")


def cmd_check_header(args: argparse.Namespace) -> None:
    pin = pin_for(args.name)
    header = check_header_file(args.path, pin)
    print(f"header ok {args.name} dmax={header['header_dmax']:.0f} dmean={header['header_dmean']:.4f}")


def cmd_check_frame(args: argparse.Namespace) -> None:
    pin = pin_for(args.name)
    header = check_header_file(args.header, pin)
    block = read_exact(args.path, FRAME_BYTES)
    stats = check_frame_bytes(block, header, pin, require_hash=False, int8_safe=False)
    if stats["maximum"] > MAX_SIGNED_SAFE:
        print(f"WARNING: {args.name} frame maximum {stats['maximum']} >= 128; build/verify will refuse it", file=sys.stderr)
    print(f"frame ok {args.name} mean={stats['mean']:.4f} max={stats['maximum']} distinct={stats['distinct_values']} sha256={stats['sha256']}")


def pin_for(name: str) -> dict[str, str]:
    matches = [pin for pin in load_pins() if pin["file_name"] == name]
    if len(matches) != 1:
        raise SourceError(f"{name} is not a pinned movie")
    return matches[0]


def cmd_inventory(args: argparse.Namespace) -> None:
    entry = check_entry(args.download_dir / "empiar_10511_entry.json")
    check_license(args.download_dir / "empiar_faq.html")
    files = []
    for pin in load_pins():
        name = pin["file_name"]
        header = check_header_file(args.download_dir / header_name(name), pin)
        block = read_exact(args.download_dir / frame_name(name), FRAME_BYTES)
        files.append({"slot": int(pin["slot"]), "file_name": name, "frame_sha256": sha256_bytes(block),
                      "header_dmean": header["header_dmean"], "header_dmax": header["header_dmax"]})
    inventory = {
        "entry": ENTRY_KEY,
        "doi": ENTRY_DOI,
        "imageset": entry,
        "license": "CC0-1.0",
        "frame_index": FRAME_INDEX,
        "byte_range": [FRAME_START, FRAME_END],
        "files": files,
        "range_bytes": len(files) * (HEADER_BYTES + FRAME_BYTES),
        "unpinned_frame_sha256": [f["slot"] for f, p in zip(files, load_pins()) if not p["frame_sha256"]],
    }
    (args.download_dir / "source_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"inventory movies={len(files)} range_bytes={inventory['range_bytes']} unpinned={len(inventory['unpinned_frame_sha256'])}")


def cmd_pin_frames(args: argparse.Namespace) -> None:
    """One-time maintenance: record whole-frame SHA-256 pins from a validated download."""
    pins = load_pins()
    for pin in pins:
        name = pin["file_name"]
        header = check_header_file(args.download_dir / header_name(name), pin)
        block = read_exact(args.download_dir / frame_name(name), FRAME_BYTES)
        stats = check_frame_bytes(block, header, pin, require_hash=False, int8_safe=False)
        pin["frame_sha256"] = stats["sha256"]
    with PINS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PIN_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(pins)
    print(f"pinned frame SHA-256 for {len(pins)} movies in {PINS_PATH.name}")


def cmd_selected(args: argparse.Namespace) -> None:
    movies = check_listing(args.listing)
    for slot, index in enumerate(selected_indices()):
        print(f"{slot}\t{index}\t{movies[index]}")


def cmd_probe_row(args: argparse.Namespace) -> None:
    if args.size != FILE_SIZE:
        raise SourceError(f"{args.name}: Content-Length {args.size} != {FILE_SIZE}")
    raw = args.header.read_bytes()
    header = parse_header(raw)
    prefix = args.prefix.read_bytes()
    if len(prefix) != PROBE_BYTES:
        raise SourceError(f"{args.name}: frame prefix probe has {len(prefix)} bytes")
    low, high = min(prefix), max(prefix)
    mean = sum(prefix) / len(prefix)
    if not (MEAN_RANGE[0] <= mean <= MEAN_RANGE[1]) or abs(mean / header["header_dmean"] - 1.0) > MAX_MEAN_DEVIATION:
        raise SourceError(f"{args.name}: frame prefix range {low}..{high} mean {mean:.3f} implausible")
    print("\t".join([str(args.slot), str(args.index), args.name, str(args.size), sha256_bytes(raw),
                     sha256_bytes(prefix), "-"]))
    print(f"probe {args.name} hdr_dmax={header['header_dmax']:.0f} hdr_dmean={header['header_dmean']:.4f} "
          f"prefix_mean={mean:.4f} prefix_max={high}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-entry"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-license"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-header"); p.add_argument("path", type=Path); p.add_argument("name")
    p = sub.add_parser("check-frame"); p.add_argument("path", type=Path); p.add_argument("header", type=Path); p.add_argument("name")
    sub.add_parser("pins")
    sub.add_parser("constants")
    p = sub.add_parser("inventory"); p.add_argument("--download-dir", type=Path, required=True)
    p = sub.add_parser("pin-frames"); p.add_argument("--download-dir", type=Path, required=True)
    p = sub.add_parser("selected"); p.add_argument("listing", type=Path)
    p = sub.add_parser("probe-row")
    for flag in ("--slot", "--index", "--size"):
        p.add_argument(flag, type=int, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--header", type=Path, required=True)
    p.add_argument("--prefix", type=Path, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--allow-unpinned", action="store_true",
                       help="accept frames whose whole-frame SHA-256 is not pinned yet (first run only)")
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "check-entry":
            print(json.dumps(check_entry(args.path)))
        elif args.command == "check-license":
            check_license(args.path)
            print("license ok: CC0")
        elif args.command == "check-header":
            cmd_check_header(args)
        elif args.command == "check-frame":
            cmd_check_frame(args)
        elif args.command == "pins":
            cmd_pins(args)
        elif args.command == "constants":
            print(f"{FILE_SIZE} {HEADER_BYTES} {FRAME_START} {FRAME_END} {FRAME_BYTES} {PROBE_BYTES}")
        elif args.command == "inventory":
            cmd_inventory(args)
        elif args.command == "pin-frames":
            cmd_pin_frames(args)
        elif args.command == "selected":
            cmd_selected(args)
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
