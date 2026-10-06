#!/usr/bin/env python3
"""EMPIAR-10994 raw SBF-SEM (Gatan 3View BSED) DM4 slices -> raw uint16 samples.

Subcommands
  selftest        synthetic-DM4 parser and validator self-test (no I/O)
  selected        print the deterministic slice selection (cell z run slice name url)
  check-entry     validate the EMPIAR entry JSON
  check-license   validate the EMPIAR FAQ CC0 sentence
  check-listing   validate a live 01_original_images Apache listing
  check-amira     validate the KD processed-stack Amira header (deleted slices)
  probe-row       discovery: validate a selected file from sparse HTTP ranges
  pins            print pinned name/url/size rows for download.sh
  check-file      validate one downloaded DM4 against its pin
  inventory       validate all downloads and write source_inventory.json
  build / verify  emit and independently re-check samples, index and stats

Pure standard library. Network I/O is done by the shell scripts with curl.
"""

from __future__ import annotations

import argparse
import array
import collections
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

sys.dont_write_bytecode = True  # keep the recipe directory free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dm4  # noqa: E402

DATASET_ID = "empiar_10994_sbfsem_bsed_slices_u16"
SERIES_ID = "hela_sbfsem_bsed_u16"
ENTRY_KEY = "EMPIAR-10994"
ENTRY_DOI = "10.6019/EMPIAR-10994"
BASE_URL = "https://ftp.ebi.ac.uk/empiar/world_availability/10994/data"
PINS_PATH = Path(__file__).resolve().parent / "slices.tsv"
LICENSE_SENTENCE = (
    "All data in EMPIAR is freely and publicly available to the global community under the CC0 license"
)

# Acquisition runs of each cell, in acquisition (and therefore z) order, with
# their slice counts in the live listings (2026-10-06).
CELLS = {
    "control": {
        "dir": "160621_HeLa_Control",
        "runs": [("r01a", 26), ("r01b", 83), ("r01c", 132), ("r01d", 131), ("r01e", 85), ("r01f", 121)],
        "voltage": 2500.0,
        "date": "21/06/2016",
        "imageset_count": 578,
    },
    "kd": {
        "dir": "161107_HeLa_REEP3-4_KD_LBR",
        "runs": [("r01", 105), ("r01b", 72), ("r01c", 82), ("r01d", 17), ("r01e", 114), ("r01f", 84)],
        "voltage": 2400.0,
        "date": "07/11/2016",
        "imageset_count": 474,
    },
}
# The depositors deleted these three frames from the KD processed stack
# (Amira header: "MIB: Delete slice: 274:276", 1-based); their DM4 metadata
# report 200 V and a 100.8 nm calibration (beam fault), so they are not part
# of the population.
EXCLUDED = {("kd", "r01d", 14), ("kd", "r01d", 15), ("kd", "r01d", 16)}
STEP = 8  # every 8th valid slice of each cell (240 nm apart in z)
Z_STEP_NM = 30.0
PIXEL_UM_RANGE = (0.0145, 0.0155)
MIN_DISTINCT = 256
MAX_MODAL_FRACTION = 0.5
# Pinned from the first verified build (2026-10-06 autocollect download); enforced.
EXPECTED_OUTPUT_DIGEST = "9197d1b64aac0f49910a52dbf772625e538cedb17358473d87c2216654250453"
REQUIRE_FILE_SHA256 = True

PIN_FIELDS = [
    "cell", "z_index", "run", "run_slice", "file_name", "size_bytes", "data_offset", "width", "height",
    "pixel_size_um", "voltage_v", "acquisition", "skeleton_sha256", "file_sha256",
]


class SourceError(RuntimeError):
    pass


# ------------------------------------------------------------------ selection


def file_name(run: str, slice_no: int) -> str:
    return f"{run}_BSED_roi_00_slice_{slice_no:04d}.dm4"


def source_url(cell: str, name: str) -> str:
    return f"{BASE_URL}/{CELLS[cell]['dir']}/01_original_images/{name}"


def valid_sequence(cell: str) -> list[tuple[str, int]]:
    seq = []
    for run, count in CELLS[cell]["runs"]:
        for s in range(count):
            if (cell, run, s) not in EXCLUDED:
                seq.append((run, s))
    return seq


def selection() -> list[dict[str, object]]:
    out = []
    for cell in CELLS:
        seq = valid_sequence(cell)
        for z in range(0, len(seq), STEP):
            run, s = seq[z]
            out.append({"cell": cell, "z_index": z, "run": run, "run_slice": s, "file_name": file_name(run, s)})
    return out


def key_of(item) -> tuple[str, int]:
    return (str(item["cell"]), int(item["z_index"]))


def load_pins() -> dict[tuple[str, int], dict[str, str]]:
    if not PINS_PATH.is_file():
        raise SourceError(f"missing pin table {PINS_PATH}")
    lines = PINS_PATH.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    if header != PIN_FIELDS:
        raise SourceError(f"pin table header {header} != {PIN_FIELDS}")
    pins = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(PIN_FIELDS, line.split("\t"), strict=True))
        pins[(row["cell"], int(row["z_index"]))] = row
    expected = selection()
    if [key_of(s) for s in expected] != list(pins):
        raise SourceError("pin table rows do not match the deterministic selection")
    for s in expected:
        p = pins[key_of(s)]
        if p["run"] != s["run"] or int(p["run_slice"]) != s["run_slice"] or p["file_name"] != s["file_name"]:
            raise SourceError(f"pin row {key_of(s)} does not match the selection")
    return pins


# ------------------------------------------------------------------ small source documents


def check_entry(path: Path) -> list[dict[str, object]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    entry = doc.get(ENTRY_KEY)
    if not isinstance(entry, dict):
        raise SourceError("entry JSON lacks EMPIAR-10994")
    if entry.get("status") != "REL" or entry.get("entry_doi") != ENTRY_DOI:
        raise SourceError("entry is not released or DOI changed")
    if entry.get("experiment_type") != "SBF-SEM":
        raise SourceError("entry experiment type is not SBF-SEM")
    if "REEP3 and REEP4" not in str(entry.get("title")):
        raise SourceError("entry title changed")
    found = []
    for cell, spec in CELLS.items():
        want = f"data/{spec['dir']}/01_original_images"
        sets = [s for s in entry.get("imagesets", []) if s.get("directory") == want]
        if len(sets) != 1:
            raise SourceError(f"imageset {want} not found exactly once")
        s = sets[0]
        if (s.get("data_format"), s.get("voxel_type"), s.get("num_images_or_tilt_series")) != (
            "DM4", "UNSIGNED 16 BIT INTEGER", spec["imageset_count"]
        ):
            raise SourceError(f"imageset {want} metadata changed: {s.get('data_format')} {s.get('voxel_type')} {s.get('num_images_or_tilt_series')}")
        found.append({"cell": cell, "directory": want, "images": s["num_images_or_tilt_series"],
                      "voxel_type": s["voxel_type"], "pixel_width_A": s.get("pixel_width")})
    return found


def check_license(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    flat = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    if LICENSE_SENTENCE not in flat:
        raise SourceError("EMPIAR FAQ no longer states the CC0 licence sentence")


def check_listing(cell: str, path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    names = set(re.findall(r'href="([^"?/]+\.dm4)"', text))
    expected = {file_name(run, s) for run, count in CELLS[cell]["runs"] for s in range(count)}
    if names != expected:
        missing = sorted(expected - names)[:5]
        extra = sorted(names - expected)[:5]
        raise SourceError(f"{cell} listing differs from the expected run structure: missing={missing} extra={extra}")
    return len(names)


def check_amira(path: Path) -> None:
    text = path.read_bytes().decode("latin-1")
    if "define Lattice 1600 1586 471" not in text or "Delete slice: 274:276" not in text:
        raise SourceError("KD processed-stack Amira header no longer documents the 274:276 slice deletion")


# ------------------------------------------------------------------ DM4 validation


def _text(root, path):
    return dm4.u16_text(dm4.lookup(root, path))


def _val(root, path):
    node = dm4.lookup(root, path)
    if not isinstance(node, dm4.Data) or node.value is None or isinstance(node.value, tuple):
        raise SourceError(f"{path} is not a scalar tag")
    return node.value


def parse_source(reader, cell: str, run: str, run_slice: int) -> dict[str, object]:
    """Walk the tag tree and enforce every structural and acquisition rule."""
    try:
        order, root = dm4.parse(reader)
        if order != 1:
            raise SourceError("DM4 byte-order flag is not little-endian")
        images = root.get("ImageList")
        if len(images.entries) != 2:
            raise SourceError(f"ImageList has {len(images.entries)} entries, expected thumbnail + image")
        thumb = dm4.image_of(dm4.image_entry(root, 0))
        if (thumb.data_type, thumb.pixel_depth) != (23, 4):
            raise SourceError(f"ImageList[0] is not the RGBA thumbnail (DataType {thumb.data_type})")
        img = dm4.image_of(dm4.image_entry(root, 1))
        if img.data_type != 10 or img.pixel_depth != 2 or img.elem_type != 4:
            raise SourceError(f"main image is not uint16: DataType={img.data_type} PixelDepth={img.pixel_depth} elem={img.elem_type}")
        if img.count != img.width * img.height or img.width < 512 or img.height < 512:
            raise SourceError(f"Data count {img.count} != {img.width}x{img.height}")
        e = "ImageList/#1/"
        cal = e + "ImageData/Calibrations/Dimension/"
        sx, sy = _val(root, cal + "#0/Scale"), _val(root, cal + "#1/Scale")
        if sx != sy or not (PIXEL_UM_RANGE[0] <= sx <= PIXEL_UM_RANGE[1]):
            raise SourceError(f"pixel calibration {sx} x {sy} um outside the ~15 nm regime")
        if _text(root, cal + "#0/Units") != "\u00b5m" or _text(root, cal + "#1/Units") != "\u00b5m":
            raise SourceError("calibration units are not um")
        t = e + "ImageTags/"
        checks = {
            "detector": (_text(root, t + "Session Info/Detector"), "3VBSED"),
            "microscope": (_text(root, t + "Microscope Info/Name"), "FEI Quanta"),
            "voltage": (_val(root, t + "Microscope Info/Voltage"), CELLS[cell]["voltage"]),
            "slice thickness": (_val(root, t + "SBFSEM/Record/Slice thickness"), Z_STEP_NM),
            "dwell": (_val(root, t + "DigiScan/Sample Time"), 20.0),
            "digiscan width": (_val(root, t + "DigiScan/Image Width"), img.width),
            "digiscan height": (_val(root, t + "DigiScan/Image Height"), img.height),
            "acquisition date": (_text(root, t + "DataBar/Acquisition Date"), CELLS[cell]["date"]),
        }
        for label, (got, want) in checks.items():
            if got != want:
                raise SourceError(f"{label} is {got!r}, expected {want!r}")
        name = _text(root, e + "Name")
        if not name.endswith(f"BSED_roi_00_slice_{run_slice:04d}"):
            raise SourceError(f"image name {name!r} does not match slice {run_slice}")
        base = _text(root, t + "SBFSEM/Record/Base file name")
        if not base.lower().endswith("\\" + run):
            raise SourceError(f"3View base file name {base!r} does not match run {run}")
        tm = _text(root, t + "DataBar/Acquisition Time")
        dd, mm, yyyy = CELLS[cell]["date"].split("/")
        if not re.fullmatch(r"\d\d:\d\d:\d\d", tm):
            raise SourceError(f"bad acquisition time {tm!r}")
        skeleton = dm4.skeleton_sha256(reader, root)
    except dm4.DM4Error as error:
        raise SourceError(f"DM4 structure: {error}") from error
    return {
        "data_offset": img.data_offset,
        "width": img.width,
        "height": img.height,
        "pixel_size_um": repr(sx),
        "voltage_v": repr(CELLS[cell]["voltage"]),
        "acquisition": f"{yyyy}-{mm}-{dd}T{tm}",
        "skeleton_sha256": skeleton,
    }


def sha256_bytes(data) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_file(path: Path, pin: dict[str, str], cell: str) -> tuple[dict[str, object], bytes]:
    buf = path.read_bytes()
    if len(buf) != int(pin["size_bytes"]):
        raise SourceError(f"{path.name}: size {len(buf)} != pinned {pin['size_bytes']}")
    layout = parse_source(dm4.BytesReader(buf), cell, pin["run"], int(pin["run_slice"]))
    for k in ("data_offset", "width", "height", "pixel_size_um", "voltage_v", "acquisition", "skeleton_sha256"):
        if str(layout[k]) != pin[k]:
            raise SourceError(f"{path.name}: {k} {layout[k]!r} != pinned {pin[k]!r}")
    file_sha = sha256_bytes(buf)
    if pin["file_sha256"] and file_sha != pin["file_sha256"]:
        raise SourceError(f"{path.name}: file SHA-256 {file_sha} != pinned {pin['file_sha256']}")
    if REQUIRE_FILE_SHA256 and not pin["file_sha256"]:
        raise SourceError(f"{path.name}: file SHA-256 is not pinned")
    off, n = int(layout["data_offset"]), 2 * int(layout["width"]) * int(layout["height"])
    report = {"cell": cell, "z_index": int(pin["z_index"]), "run": pin["run"], "run_slice": int(pin["run_slice"]),
              "file_name": pin["file_name"], "source_size_bytes": len(buf), "file_sha256": file_sha, **layout}
    return report, buf[off:off + n]


# ------------------------------------------------------------------ pixel stats


def as_u16(block: bytes) -> array.array:
    a = array.array("H")
    a.frombytes(block)
    if sys.byteorder != "little":
        a.byteswap()
    return a


def pixel_stats(block: bytes, width: int, height: int) -> dict[str, object]:
    if len(block) != 2 * width * height:
        raise SourceError("pixel block has the wrong size")
    a = as_u16(block)
    hist = collections.Counter(a)
    total = len(a)
    modal_value, modal_count = max(hist.items(), key=lambda kv: (kv[1], -kv[0]))
    constant_rows = sum(1 for r in range(height) if len(set(a[r * width:(r + 1) * width])) == 1)
    constant_cols = sum(1 for c in range(width) if len(set(a[c::width])) == 1)
    stats = {
        "minimum": min(hist),
        "maximum": max(hist),
        "distinct_values": len(hist),
        "mean": round(sum(v * c for v, c in hist.items()) / total, 6),
        "zero_values": hist.get(0, 0),
        "max_values": hist.get(65535, 0),
        "modal_value": modal_value,
        "modal_fraction": round(modal_count / total, 9),
        "constant_rows": constant_rows,
        "constant_cols": constant_cols,
        "high_byte_distinct": len({v >> 8 for v in hist}),
        "zlib1_ratio": round(len(zlib.compress(block, 1)) / total / 2, 6),
        "sha256": sha256_bytes(block),
    }
    problems = []
    if stats["minimum"] == stats["maximum"]:
        problems.append("constant frame")
    if stats["distinct_values"] < MIN_DISTINCT:
        problems.append(f"only {stats['distinct_values']} distinct values")
    if stats["modal_fraction"] > MAX_MODAL_FRACTION:
        problems.append(f"modal value covers {stats['modal_fraction']:.3f} of pixels")
    if constant_rows or constant_cols:
        problems.append(f"{constant_rows} constant rows / {constant_cols} constant columns")
    if stats["maximum"] < 256:
        problems.append("all values fit in 8 bits")
    if problems:
        raise SourceError("degenerate frame: " + "; ".join(problems))
    return stats


STAT_KEYS = ["minimum", "maximum", "distinct_values", "mean", "zero_values", "max_values", "modal_value",
             "modal_fraction", "constant_rows", "constant_cols", "high_byte_distinct", "zlib1_ratio", "sha256"]


# ------------------------------------------------------------------ build / verify


def output_name(r: dict[str, object]) -> str:
    return (f"{r['cell']}_z{int(r['z_index']):03d}_{r['run']}_s{int(r['run_slice']):04d}"
            f"_h{r['height']}_w{r['width']}_u16.bin")


def scan_all(download_dir: Path) -> list[dict[str, object]]:
    pins = load_pins()
    check_entry(download_dir / "empiar_10994_entry.json")
    check_license(download_dir / "empiar_faq.html")
    reports, seen = [], set()
    for (cell, z), pin in pins.items():
        source = download_dir / cell / pin["file_name"]
        report, block = validate_file(source, pin, cell)
        try:
            stats = pixel_stats(block, int(report["width"]), int(report["height"]))
        except SourceError as error:
            raise SourceError(f"{cell}/{source.name}: {error}") from error
        if stats["sha256"] in seen:
            raise SourceError(f"{cell}/{source.name}: duplicate pixel payload")
        seen.add(stats["sha256"])
        reports.append({**report, **stats})
        print(f"{cell} z={z:03d} {pin['file_name']} {report['width']}x{report['height']} off={report['data_offset']} "
              f"min={stats['minimum']} max={stats['maximum']} distinct={stats['distinct_values']} "
              f"mean={stats['mean']:.1f} zlib1={stats['zlib1_ratio']}", flush=True)
    return reports


def summarize(reports: list[dict[str, object]]) -> dict[str, object]:
    ratios = [float(r["zlib1_ratio"]) for r in reports]
    values = sum(int(r["width"]) * int(r["height"]) for r in reports)
    shapes = collections.Counter(f"{r['height']}x{r['width']}" for r in reports)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(reports),
        "samples_per_cell": dict(collections.Counter(str(r["cell"]) for r in reports)),
        "samples_per_run": dict(collections.Counter(f"{r['cell']}/{r['run']}" for r in reports)),
        "shapes": dict(sorted(shapes.items())),
        "value_count": values,
        "total_size_bytes": 2 * values,
        "median_sample_values": statistics.median(int(r["width"]) * int(r["height"]) for r in reports),
        "unique_payloads": len({r["sha256"] for r in reports}),
        "global_minimum": min(int(r["minimum"]) for r in reports),
        "global_maximum": max(int(r["maximum"]) for r in reports),
        "minimum_distinct_values": min(int(r["distinct_values"]) for r in reports),
        "zero_values": sum(int(r["zero_values"]) for r in reports),
        "max_values": sum(int(r["max_values"]) for r in reports),
        "maximum_modal_fraction": max(float(r["modal_fraction"]) for r in reports),
        "odd_data_offsets": sum(1 for r in reports if int(r["data_offset"]) % 2),
        "minimum_zlib1_ratio": min(ratios),
        "median_zlib1_ratio": statistics.median(ratios),
        "maximum_zlib1_ratio": max(ratios),
        "output_digest": hashlib.sha256(
            "".join(f"{output_name(r)}\t{r['sha256']}\n" for r in reports).encode()).hexdigest(),
    }
    if EXPECTED_OUTPUT_DIGEST and summary["output_digest"] != EXPECTED_OUTPUT_DIGEST:
        raise SourceError(f"output digest {summary['output_digest']} != pinned {EXPECTED_OUTPUT_DIGEST}")
    return summary


def index_row(r: dict[str, object], sample_path: str) -> dict[str, object]:
    w, h = int(r["width"]), int(r["height"])
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_path,
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": 2 * w * h,
        "value_count": w * h,
        "sample_format": "raw homogeneous little-endian uint16 SBF-SEM backscattered-electron block-face image",
        "sample_geometry": "sbfsem_block_face_scan_raster_2d",
        "sample_rank": 2,
        "sample_shape": [h, w],
        "sample_axes": ["scan_line_y", "scan_pixel_x"],
        "natural_record_kind": "sbfsem_block_face_slice_dm4",
        "source_url": source_url(str(r["cell"]), str(r["file_name"])),
        "source_file": r["file_name"],
        "source_size_bytes": r["source_size_bytes"],
        "source_file_sha256": r["file_sha256"],
        "source_data_offset": r["data_offset"],
        "cell": r["cell"],
        "acquisition_run": r["run"],
        "run_slice": r["run_slice"],
        "z_index": r["z_index"],
        "z_depth_um": round(int(r["z_index"]) * Z_STEP_NM / 1000.0, 2),
        "pixel_size_nm": round(float(r["pixel_size_um"]) * 1000.0, 4),
        "voltage_v": float(r["voltage_v"]),
        "acquisition_datetime": r["acquisition"],
        "minimum": r["minimum"],
        "maximum": r["maximum"],
        "distinct_values": r["distinct_values"],
        "mean": r["mean"],
        "sha256": r["sha256"],
    }


def build(args: argparse.Namespace) -> None:
    selftest(quiet=True)
    reports = scan_all(args.download_dir)
    summary = summarize(reports)
    series_dir = args.data_root / "samples" / DATASET_ID / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    pins = load_pins()
    for r in reports:
        _, block = validate_file(args.download_dir / str(r["cell"]) / str(r["file_name"]), pins[key_of(r)], str(r["cell"]))
        if sha256_bytes(block) != r["sha256"]:
            raise SourceError(f"source changed during build: {r['file_name']}")
        out = series_dir / output_name(r)
        out.write_bytes(block)
        rows.append(index_row(r, out.relative_to(args.data_root).as_posix()))
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    stats_path = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps({**summary, "frames": reports}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    selftest(quiet=True)
    reports = scan_all(args.download_dir)  # independent re-derivation from the DM4 files
    summary = summarize(reports)
    index_path = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index_path.is_file() or not stats_path.is_file():
        raise SourceError("missing index or ingest stats; run build.sh first")
    rows = [json.loads(x) for x in index_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(rows) != len(reports):
        raise SourceError(f"index has {len(rows)} rows, expected {len(reports)}")
    pins = load_pins()
    expected_paths = set()
    for row, r in zip(rows, reports, strict=True):
        want = json.loads(json.dumps(index_row(r, f"samples/{DATASET_ID}/{SERIES_ID}/{output_name(r)}")))
        if row != want:
            diff = sorted(k for k in set(row) | set(want) if row.get(k) != want.get(k))
            raise SourceError(f"index row mismatch for {r['file_name']}: {diff}")
        out = args.data_root / row["sample_path"]
        expected_paths.add(out.resolve())
        if not out.is_file() or out.stat().st_size != row["sample_size_bytes"]:
            raise SourceError(f"missing or mis-sized sample {out}")
        data = out.read_bytes()
        _, block = validate_file(args.download_dir / str(r["cell"]) / str(r["file_name"]), pins[key_of(r)], str(r["cell"]))
        if data != block:
            raise SourceError(f"sample {out.name} is not the source Data array")
        if pixel_stats(data, int(r["width"]), int(r["height"])) != {k: r[k] for k in STAT_KEYS}:
            raise SourceError(f"sample statistics differ for {out.name}")
    actual = {p.resolve() for p in (args.data_root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if actual != expected_paths:
        raise SourceError("sample directory contents do not match the index")
    stored = json.loads(stats_path.read_text(encoding="utf-8"))
    for k, v in summary.items():
        if stored.get(k) != json.loads(json.dumps(v)):
            raise SourceError(f"ingest statistic {k} differs: {stored.get(k)!r} != {v!r}")
    if stored.get("frames") != json.loads(json.dumps(reports)):
        raise SourceError("stored per-frame reports differ")
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = manifest.get("series", [])
    if len(series) != 1 or series[0].get("id") != SERIES_ID or series[0].get("role") != "primary":
        raise SourceError("manifest must declare exactly the one primary series")
    if int(series[0]["sample_count"]) != summary["sample_count"] or int(series[0]["total_size_bytes"]) != summary["total_size_bytes"]:
        raise SourceError("manifest sample_count/total_size_bytes do not match realized output")
    if summary["unique_payloads"] != summary["sample_count"]:
        raise SourceError("duplicate payloads")
    if summary["total_size_bytes"] > 1_000_000_000:
        raise SourceError("primary output exceeds the 1 GB cap")
    print(json.dumps({"dataset_id": DATASET_ID, "verified_samples": summary["sample_count"],
                      "verified_values": summary["value_count"], "verified_bytes": summary["total_size_bytes"],
                      "output_digest": summary["output_digest"]}, indent=2, sort_keys=True))


# ------------------------------------------------------------------ download / discovery helpers


def cmd_pins(args) -> None:
    for (cell, z), p in load_pins().items():
        print(f"{cell}\t{z}\t{p['file_name']}\t{source_url(cell, p['file_name'])}\t{p['size_bytes']}")


def cmd_selected(args) -> None:
    for s in selection():
        print(f"{s['cell']}\t{s['z_index']}\t{s['run']}\t{s['run_slice']}\t{s['file_name']}\t{source_url(str(s['cell']), str(s['file_name']))}")


def cmd_check_file(args) -> None:
    pins = load_pins()
    pin = pins.get((args.cell, args.z))
    if pin is None:
        raise SourceError(f"{args.cell} z={args.z} is not a selected slice")
    report, block = validate_file(args.path, pin, args.cell)
    a = as_u16(block)
    if min(a) == max(a):
        raise SourceError(f"{args.path.name}: constant image")
    print(f"ok {args.cell}/{pin['file_name']} {report['width']}x{report['height']} off={report['data_offset']} sha256={report['file_sha256']}")


def cmd_inventory(args) -> None:
    pins = load_pins()
    entry = check_entry(args.download_dir / "empiar_10994_entry.json")
    check_license(args.download_dir / "empiar_faq.html")
    files = []
    for (cell, z), pin in pins.items():
        report, _ = validate_file(args.download_dir / cell / pin["file_name"], pin, cell)
        files.append({k: report[k] for k in ("cell", "z_index", "file_name", "source_size_bytes", "file_sha256", "acquisition")})
    inv = {"entry": ENTRY_KEY, "doi": ENTRY_DOI, "imagesets": entry, "license": "CC0-1.0",
           "files": files, "download_bytes": sum(int(f["source_size_bytes"]) for f in files),
           "unpinned_file_sha256": [f"{f['cell']}/{f['file_name']}" for f in files if not pins[(f["cell"], f["z_index"])]["file_sha256"]]}
    (args.download_dir / "source_inventory.json").write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")
    print(f"inventory files={len(files)} bytes={inv['download_bytes']} unpinned_sha256={len(inv['unpinned_file_sha256'])}")


class NeedBytes(Exception):
    pass


class SparseReader:
    """Reader over a few fetched byte ranges of a remote file (discovery only)."""

    def __init__(self, size: int, segments: list[tuple[int, bytes]]):
        self.size = size
        merged: list[list] = []
        for start, data in sorted(segments):
            if merged and start <= merged[-1][0] + len(merged[-1][1]):
                prev_start, prev = merged[-1]
                prev_end = prev_start + len(prev)
                if start + len(data) > prev_end:
                    merged[-1][1] = prev + data[prev_end - start:]
            else:
                merged.append([start, bytes(data)])
        self.segments = [(s, bytes(d)) for s, d in merged]

    def read(self, off: int, n: int) -> bytes:
        if off < 0 or off + n > self.size:
            raise dm4.DM4Error(f"read past end: off={off} n={n}")
        for start, data in self.segments:
            if start <= off and off + n <= start + len(data):
                return data[off - start:off - start + n]
        raise NeedBytes((off, n))


def cmd_probe_row(args) -> None:
    segments = []
    for p in sorted(args.seg_dir.glob("seg_*.bin")):
        segments.append((int(p.stem.split("_")[1]), p.read_bytes()))
    reader = SparseReader(args.size, segments)
    try:
        layout = parse_source(reader, args.cell, args.run, args.run_slice)
    except NeedBytes as need:
        off, n = need.args[0]
        end = min(args.size, off + max(n, 65536))
        print(f"need {off} {end - 1}")
        sys.exit(3)
    row = {"cell": args.cell, "z_index": args.z, "run": args.run, "run_slice": args.run_slice,
           "file_name": file_name(args.run, args.run_slice), "size_bytes": args.size, **layout, "file_sha256": ""}
    print("\t".join(str(row[k]) for k in PIN_FIELDS))


# ------------------------------------------------------------------ synthetic self-test


def _tag_data(name: bytes, info: list[int], value: bytes) -> bytes:
    body = b"%%%%" + struct.pack(">Q", len(info)) + struct.pack(f">{len(info)}Q", *info) + value
    return bytes([0x15]) + struct.pack(">H", len(name)) + name + struct.pack(">Q", len(body)) + body


def _tag_group(name: bytes, children: list[bytes]) -> bytes:
    body = bytes([1, 0]) + struct.pack(">Q", len(children)) + b"".join(children)
    return bytes([0x14]) + struct.pack(">H", len(name)) + name + struct.pack(">Q", len(body)) + body


def _u32(name: bytes, v: int) -> bytes:
    return _tag_data(name, [5], struct.pack("<I", v))


def _f32(name: bytes, v: float) -> bytes:
    return _tag_data(name, [6], struct.pack("<f", v))


def _f64(name: bytes, v: float) -> bytes:
    return _tag_data(name, [7], struct.pack("<d", v))


def _text_tag(name: bytes, s: str) -> bytes:
    return _tag_data(name, [20, 4, len(s)], struct.pack(f"<{len(s)}H", *map(ord, s)))


def _image_data(width: int, height: int, data_type: int, depth: int, elem: int, payload: bytes,
                scale: float, units: str, count: int | None = None) -> bytes:
    n = width * height if count is None else count
    dim = lambda: _tag_group(b"", [_f32(b"Origin", 0.0), _f32(b"Scale", scale), _text_tag(b"Units", units)])  # noqa: E731
    return _tag_group(b"ImageData", [
        _tag_group(b"Calibrations", [
            _tag_group(b"Brightness", [_f32(b"Origin", 0.0), _f32(b"Scale", 1.0), _text_tag(b"Units", "")]),
            _tag_group(b"Dimension", [dim(), dim()]),
            _tag_data(b"DisplayCalibratedUnits", [8], b"\x01"),
        ]),
        _tag_data(b"Data", [20, elem, n], payload[:n * dm4.SIMPLE[elem][1]]),
        _u32(b"DataType", data_type),
        _tag_group(b"Dimensions", [_u32(b"", width), _u32(b"", height)]),
        _u32(b"PixelDepth", depth),
    ])


def synthetic_dm4(width=600, height=520, pad=b"Pad", voltage=2500.0,
                  scale=0.0149166, data_type=10, depth=2, elem=4, count=None, run="r01c", slice_no=7,
                  date="21/06/2016", seed=1):
    """Return (file bytes, pixel values) for a DM4 shaped like the 3View files."""
    vals = [(20000 + (x * 7 + y * 13 + (x * y * seed) % 997) % 9000) for y in range(height) for x in range(width)]
    payload = struct.pack(f"<{len(vals)}H", *vals)
    tw, th = 64, 64
    thumb = struct.pack(f"<{tw * th}i", *[(-1 - i) for i in range(tw * th)])
    entry0 = _tag_group(b"", [
        _image_data(tw, th, 23, 4, 3, thumb, 1.0, ""),
        _tag_group(b"ImageTags", [_tag_data(pad, [8], b"\x01")]),
        _text_tag(b"Name", "Image Of BSED_roi_00_slice_0007"),
        _tag_group(b"UniqueID", [_u32(b"", 1), _u32(b"", 2), _u32(b"", 3), _u32(b"", 4)]),
    ])
    tags = _tag_group(b"ImageTags", [
        _tag_group(b"DataBar", [_text_tag(b"Acquisition Date", date), _text_tag(b"Acquisition Time", "15:43:32")]),
        _tag_group(b"DigiScan", [_tag_data(b"Bitshift", [2], struct.pack("<h", 6)), _u32(b"Image Height", height),
                                 _u32(b"Image Width", width), _f64(b"Sample Time", 20.0)]),
        _tag_group(b"Microscope Info", [_text_tag(b"Name", "FEI Quanta"), _f64(b"Voltage", voltage)]),
        _tag_group(b"SBFSEM", [_tag_group(b"Record", [
            _text_tag(b"Base file name", f"D:\\3View\\x\\{run.upper()}\\{run}"),
            _f64(b"Slice thickness", 30.0)])]),
        _tag_group(b"Session Info", [_text_tag(b"Detector", "3VBSED"),
                                     _tag_data(b"Note", [18, 6], "abc".encode("utf-16-le"))]),
    ])
    entry1 = _tag_group(b"", [
        _text_tag(b"Description", "pixel size :  0.0149\u00b5m"),
        _image_data(width, height, data_type, depth, elem, payload, scale, "\u00b5m", count),
        tags,
        _text_tag(b"Name", f"BSED_roi_00_slice_{slice_no:04d}"),
        _tag_group(b"UniqueID", [_u32(b"", 5), _u32(b"", 6), _u32(b"", 7), _u32(b"", 8)]),
    ])
    clut = struct.pack("<768h", *([0] * 768))
    children = [
        _tag_data(b"ApplicationBounds", [15, 0, 4, 0, 11, 0, 11, 0, 11, 0, 11], struct.pack("<4q", 0, 0, 854, 1410)),
        _tag_group(b"DocumentObjectList", [_tag_group(b"", [
            _tag_data(b"CLUT", [20, 15, 0, 3, 0, 2, 0, 2, 0, 2, 256], clut),
            _tag_data(b"BackgroundColor", [15, 0, 3, 0, 2, 0, 2, 0, 2], struct.pack("<3h", -1, -1, -1))])]),
        _tag_group(b"ImageList", [entry0, entry1]),
        _tag_data(b"InImageMode", [8], b"\x01"),
        _tag_group(b"PageSetup", [_tag_data(b"Win32", [20, 10, 5], b"\x08\x00\x00\x00\x56")]),
    ]
    root_body = bytes([1, 0]) + struct.pack(">Q", len(children)) + b"".join(children)
    blob = struct.pack(">IQI", 4, len(root_body), 1) + root_body + b"\0" * 8
    return blob, vals


def selftest(quiet: bool = False) -> None:
    def expect_fail(label, fn):
        try:
            fn()
        except (SourceError, dm4.DM4Error):
            return
        raise AssertionError(f"selftest: {label} was accepted")

    results = []
    for pad in (b"Pad", b"Pads"):
        blob, vals = synthetic_dm4(pad=pad)
        layout = parse_source(dm4.BytesReader(blob), "control", "r01c", 7)
        off, w, h = int(layout["data_offset"]), int(layout["width"]), int(layout["height"])
        assert (w, h) == (600, 520), (w, h)
        got = list(as_u16(blob[off:off + 2 * w * h]))
        assert got == vals, "decoded pixels differ from the synthetic payload"
        shifted = list(as_u16(blob[off + 1:off + 1 + 2 * w * h - 2]))
        assert shifted != vals[:-1], "misaligned decode unexpectedly matched"
        pixel_stats(blob[off:off + 2 * w * h], w, h)
        results.append(off % 2)
    # The two tag names differ by one byte, so one layout puts Data at an odd offset.
    assert sorted(results) == [0, 1], f"offset parity coverage failed: {results}"
    # Skeleton digest ignores pixel content but not metadata.
    a, _ = synthetic_dm4(seed=1)
    b, _ = synthetic_dm4(seed=2)
    c, _ = synthetic_dm4(seed=1, voltage=2500.0, date="21/06/2016", slice_no=7, run="r01c", scale=0.0149167)
    sa = parse_source(dm4.BytesReader(a), "control", "r01c", 7)["skeleton_sha256"]
    sb = parse_source(dm4.BytesReader(b), "control", "r01c", 7)["skeleton_sha256"]
    sc = parse_source(dm4.BytesReader(c), "control", "r01c", 7)["skeleton_sha256"]
    assert sa == sb and sa != sc, "skeleton digest semantics"
    assert a != b
    # Sparse range reader reproduces the full parse from small segments.
    size = len(a)
    segs = [(0, a[:4096]), (size - 2048, a[-2048:])]
    for _ in range(20):
        try:
            sp = parse_source(SparseReader(size, segs), "control", "r01c", 7)
            break
        except NeedBytes as need:
            off, n = need.args[0]
            segs.append((off, a[off:off + max(n, 1024)]))
    else:
        raise AssertionError("sparse probe did not converge")
    full = parse_source(dm4.BytesReader(a), "control", "r01c", 7)
    assert sp == full, "sparse-range parse differs from the full-file parse"
    fetched = sum(len(d) for _, d in SparseReader(size, segs).segments)
    assert fetched < size // 4, f"sparse probe fetched {fetched} of {size} bytes"
    # Rejections.
    expect_fail("uint8 main image", lambda: parse_source(dm4.BytesReader(synthetic_dm4(data_type=6, depth=1, elem=10)[0]), "control", "r01c", 7))
    expect_fail("RGB main image", lambda: parse_source(dm4.BytesReader(synthetic_dm4(data_type=23)[0]), "control", "r01c", 7))
    expect_fail("count mismatch", lambda: parse_source(dm4.BytesReader(synthetic_dm4(width=600, height=520, count=600 * 519)[0]), "control", "r01c", 7))
    expect_fail("HV-fault frame", lambda: parse_source(dm4.BytesReader(synthetic_dm4(voltage=200.0, scale=0.1008)[0]), "control", "r01c", 7))
    expect_fail("wrong cell voltage", lambda: parse_source(dm4.BytesReader(a), "kd", "r01c", 7))
    expect_fail("wrong slice", lambda: parse_source(dm4.BytesReader(a), "control", "r01c", 8))
    expect_fail("wrong run", lambda: parse_source(dm4.BytesReader(a), "control", "r01d", 7))
    bad = bytearray(a)
    bad[11] ^= 1  # root length
    expect_fail("root length", lambda: parse_source(dm4.BytesReader(bytes(bad)), "control", "r01c", 7))
    expect_fail("truncated", lambda: parse_source(dm4.BytesReader(a[:-1]), "control", "r01c", 7))
    idx = a.find(b"DataType") + len(b"DataType") + 7  # low byte of the DataType tag length
    bad = bytearray(a)
    bad[idx] += 1
    expect_fail("tag length", lambda: parse_source(dm4.BytesReader(bytes(bad)), "control", "r01c", 7))
    flat = array.array("H", [30000] * (600 * 520)).tobytes()
    expect_fail("constant frame", lambda: pixel_stats(flat, 600, 520))
    if not quiet:
        print(f"selftest ok: data offsets parity={results}, sparse probe fetched {fetched}/{size} bytes")


# ------------------------------------------------------------------ CLI


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    sub.add_parser("selected")
    sub.add_parser("pins")
    p = sub.add_parser("check-entry"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-license"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-listing"); p.add_argument("cell", choices=sorted(CELLS)); p.add_argument("path", type=Path)
    p = sub.add_parser("check-amira"); p.add_argument("path", type=Path)
    p = sub.add_parser("check-file"); p.add_argument("path", type=Path); p.add_argument("cell", choices=sorted(CELLS)); p.add_argument("z", type=int)
    p = sub.add_parser("inventory"); p.add_argument("--download-dir", type=Path, required=True)
    p = sub.add_parser("probe-row")
    for name, typ in (("--cell", str), ("--z", int), ("--run", str), ("--run-slice", int), ("--size", int), ("--seg-dir", Path)):
        p.add_argument(name, type=typ, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args()
    try:
        if args.cmd == "selftest":
            selftest()
        elif args.cmd == "selected":
            cmd_selected(args)
        elif args.cmd == "pins":
            cmd_pins(args)
        elif args.cmd == "check-entry":
            for s in check_entry(args.path):
                print(f"entry ok: {s}")
        elif args.cmd == "check-license":
            check_license(args.path)
            print("license ok: CC0")
        elif args.cmd == "check-listing":
            print(f"listing ok: {args.cell} {check_listing(args.cell, args.path)} DM4 files")
        elif args.cmd == "check-amira":
            check_amira(args.path)
            print("amira ok: KD processed stack is 471 slices with 274:276 deleted")
        elif args.cmd == "check-file":
            cmd_check_file(args)
        elif args.cmd == "inventory":
            cmd_inventory(args)
        elif args.cmd == "probe-row":
            cmd_probe_row(args)
        elif args.cmd == "build":
            build(args)
        elif args.cmd == "verify":
            verify(args)
    except SourceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
