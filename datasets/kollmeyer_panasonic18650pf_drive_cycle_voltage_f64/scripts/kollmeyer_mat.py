#!/usr/bin/env python3
"""Decode Kollmeyer Panasonic 18650PF drive-cycle MAT v5 files.

Pure standard library. Subcommands:
  selftest   round-trip the MAT v5 parser on synthetic files
  preflight  validate downloaded evidence files, mirror tree and MAT payloads
  build      emit one little-endian float64 Voltage sample per drive-cycle file
  verify     re-decode every source and compare against samples and index
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import struct
import sys
import tempfile
import tomllib
import zlib


DATASET_ID = "kollmeyer_panasonic18650pf_drive_cycle_voltage_f64"
SERIES_ID = "cell_terminal_voltage_f64"
REVISION = "0f3c96601aa8dcc25f697ef32f3ac918d24433b9"
REPO_ROOT_PREFIX = "Panasonic 18650PF Data/"
EXPECTED_SELECTED = 55
EXPECTED_SOURCE_BYTES = 113_217_590
EXPECTED_EXCLUDED = 28
# Realized output at the pinned revision (all 55 files decoded on 2026-10-05).
EXPECTED_TOTAL_VALUES = 4_452_992
EVIDENCE = {
    "mirror_readme": (
        "mirror_README.md",
        2_190,
        "f33e6b30bfb127851de3165c797d7c5f8625e9f4f60bcf45bf0b55f91d4050c0",
    ),
    "upstream_readme": (
        "upstream_readme_desc_of_tests.txt",
        6_426,
        "ed236fbbc93b3ac6fba2d0a98c55d5572fbe31b1053dc1ce46c8e268a1c23aab",
    ),
}
TREE_NAME = f"hf_tree_{REVISION}.json"
# Folders whose .mat files are fully accounted for by selection.tsv + excluded.tsv.
COVERED_FOLDERS = {
    "25degC/Drive cycles",
    "10degC/Drive Cycles",
    "0degC/Drive cycles",
    "-10degC/Drive Cycles",
    "-20degC/Drive cycles",
    "-20degC Trise",
    "10degC Trise",
}
PROFILES = {"Cycle_1", "Cycle_2", "Cycle_3", "Cycle_4", "US06", "HWFET", "HWFTa", "HWFTb", "UDDS", "LA92", "NN"}
AMBIENTS = {"25degC", "10degC", "0degC", "-10degC", "-20degC", "-20degC_trise", "10degC_trise"}

# Acceptance thresholds shared by build and verify. The upper bound leaves room
# for regen pulses near full charge at 10/25 degC (observed max 4.32296 V in
# 10degC_LA92 at +6.6 A); observed global range is 2.28588..4.32296 V.
V_MIN, V_MAX = 2.0, 4.4
MIN_VALUES_PER_FILE = 1_000
MIN_DISTINCT_PER_FILE = 500
NOMINAL_DT = 0.1
NOMINAL_TOL = 0.02
MEDIAN_DT_RANGE = (0.095, 0.105)
MIN_NOMINAL_FRACTION = 0.90

# MAT v5 constants.
MI_INT8, MI_UINT8, MI_INT16, MI_UINT16, MI_INT32, MI_UINT32 = 1, 2, 3, 4, 5, 6
MI_SINGLE, MI_DOUBLE, MI_INT64, MI_UINT64 = 7, 9, 12, 13
MI_MATRIX, MI_COMPRESSED, MI_UTF8, MI_UTF16, MI_UTF32 = 14, 15, 16, 17, 18
MX_CELL, MX_STRUCT, MX_OBJECT, MX_CHAR, MX_SPARSE, MX_DOUBLE = 1, 2, 3, 4, 5, 6
FLAG_COMPLEX = 0x0800


class MatError(ValueError):
    pass


# ---------------------------------------------------------------- MAT parser

def iter_elements(data: bytes, *, top_level: bool = False):
    """Yield (type, payload) for consecutive MAT v5 data elements.

    Handles the packed small-data-element form (upper 16 bits of the first
    tag word hold the byte count, 1..4 bytes of data in the same 8 bytes) and
    8-byte padding. Top-level miCOMPRESSED elements are not padded.
    """
    offset = 0
    size_total = len(data)
    while offset < size_total:
        if size_total - offset < 8:
            if any(data[offset:]):
                raise MatError("nonzero trailing bytes after last MAT element")
            return
        word = struct.unpack_from("<I", data, offset)[0]
        if word >> 16:
            element_type = word & 0xFFFF
            nbytes = word >> 16
            if nbytes > 4:
                raise MatError(f"invalid small data element size {nbytes}")
            yield element_type, data[offset + 4:offset + 4 + nbytes]
            offset += 8
            continue
        element_type = word
        nbytes = struct.unpack_from("<I", data, offset + 4)[0]
        start = offset + 8
        if start + nbytes > size_total:
            raise MatError(f"truncated MAT element type={element_type} size={nbytes}")
        yield element_type, data[start:start + nbytes]
        if top_level and element_type == MI_COMPRESSED:
            offset = start + nbytes
        else:
            offset = start + ((nbytes + 7) // 8) * 8


def inflate(payload: bytes) -> bytes:
    decoder = zlib.decompressobj()
    try:
        out = decoder.decompress(payload) + decoder.flush()
    except zlib.error as error:
        raise MatError(f"invalid miCOMPRESSED stream: {error}") from error
    if not decoder.eof or decoder.unused_data:
        raise MatError("miCOMPRESSED stream incomplete or followed by extra bytes")
    return out


def parse_matrix(payload: bytes) -> dict:
    """Parse an miMATRIX payload into a small dict (recursing into structs)."""
    if not payload:
        return {"class": None, "dims": (0, 0), "name": "", "empty": True}
    parts = list(iter_elements(payload))
    if len(parts) < 3:
        raise MatError("miMATRIX has fewer than 3 subelements")
    (flag_type, flag_bytes), (dim_type, dim_bytes), (name_type, name_bytes) = parts[:3]
    if flag_type != MI_UINT32 or len(flag_bytes) != 8:
        raise MatError("invalid array flags subelement")
    flags = struct.unpack_from("<I", flag_bytes)[0]
    mx_class = flags & 0xFF
    if dim_type != MI_INT32 or not dim_bytes or len(dim_bytes) % 4:
        raise MatError("invalid dimensions subelement")
    dims = struct.unpack("<%di" % (len(dim_bytes) // 4), dim_bytes)
    if any(value < 0 for value in dims):
        raise MatError(f"negative dimensions {dims}")
    if name_type != MI_INT8:
        raise MatError("invalid array name subelement")
    name = name_bytes.decode("ascii")
    out = {"class": mx_class, "flags": flags, "dims": dims, "name": name, "empty": False}
    rest = parts[3:]
    if mx_class == MX_STRUCT:
        if len(rest) < 2 or rest[0][0] != MI_INT32 or len(rest[0][1]) != 4:
            raise MatError("struct lacks field-name-length subelement")
        name_len = struct.unpack("<i", rest[0][1])[0]
        if rest[1][0] != MI_INT8 or name_len <= 0 or len(rest[1][1]) % name_len:
            raise MatError("struct field-name array malformed")
        raw_names = rest[1][1]
        names = [
            raw_names[i:i + name_len].split(b"\0", 1)[0].decode("ascii")
            for i in range(0, len(raw_names), name_len)
        ]
        if len(set(names)) != len(names):
            raise MatError(f"duplicate struct field names {names}")
        count = math.prod(dims)
        values = rest[2:]
        if len(values) != count * len(names):
            raise MatError("struct field matrix count mismatch")
        fields = {}
        if count == 1:
            for field_name, (element_type, sub) in zip(names, values):
                if element_type != MI_MATRIX:
                    raise MatError(f"struct field {field_name} is not miMATRIX")
                fields[field_name] = sub
        out["field_names"] = names
        out["fields"] = fields
    elif mx_class == MX_CELL:
        count = math.prod(dims)
        if len(rest) != count or any(element_type != MI_MATRIX for element_type, _ in rest):
            raise MatError("cell array element count/type mismatch")
        out["cell_count"] = count
    elif mx_class in (MX_OBJECT, MX_SPARSE):
        out["opaque"] = True
    else:
        if not rest:
            raise MatError(f"numeric array {name!r} lacks real-part data")
        out["data_type"], out["data"] = rest[0]
        out["complex"] = bool(flags & FLAG_COMPLEX)
        if out["complex"] and len(rest) < 2:
            raise MatError("complex array lacks imaginary part")
    return out


def read_meas(path: Path) -> dict:
    """Return the parsed 1x1 struct variable 'meas' from a MAT v5 file."""
    raw = path.read_bytes()
    if len(raw) < 136 or not raw.startswith(b"MATLAB 5.0 MAT-file"):
        raise MatError("not a MATLAB 5.0 MAT-file")
    version, endian = struct.unpack_from("<H2s", raw, 124)
    if endian != b"IM" or version != 0x0100:
        raise MatError(f"unsupported MAT header version={version:#x} endian={endian!r}")
    variables = {}
    for element_type, payload in iter_elements(raw[128:], top_level=True):
        if element_type == MI_COMPRESSED:
            inner = list(iter_elements(inflate(payload)))
            if len(inner) != 1 or inner[0][0] != MI_MATRIX:
                raise MatError("miCOMPRESSED element does not hold exactly one miMATRIX")
            matrix_payload = inner[0][1]
        elif element_type == MI_MATRIX:
            matrix_payload = payload
        else:
            raise MatError(f"unexpected top-level element type {element_type}")
        matrix = parse_matrix(matrix_payload)
        if matrix["name"] in variables:
            raise MatError(f"duplicate MAT variable {matrix['name']!r}")
        variables[matrix["name"]] = matrix
    meas = variables.get("meas")
    if meas is None or meas["class"] != MX_STRUCT or tuple(meas["dims"]) != (1, 1):
        raise MatError(f"no 1x1 struct 'meas' (variables: {sorted(variables)})")
    return meas


def double_column(meas: dict, field: str) -> tuple[bytes, int]:
    """Return (little-endian float64 bytes, N) for an N x 1 mxDOUBLE/miDOUBLE field."""
    if field not in meas["fields"]:
        raise MatError(f"meas lacks field {field!r} (fields: {meas['field_names']})")
    matrix = parse_matrix(meas["fields"][field])
    if matrix["empty"] or matrix["class"] != MX_DOUBLE:
        raise MatError(f"{field}: not an mxDOUBLE array")
    if matrix["complex"]:
        raise MatError(f"{field}: complex array")
    dims = tuple(matrix["dims"])
    if len(dims) != 2 or dims[1] != 1 or dims[0] < 1:
        raise MatError(f"{field}: dims {dims} are not N x 1")
    if matrix["data_type"] != MI_DOUBLE:
        raise MatError(f"{field}: stored as MAT type {matrix['data_type']}, not miDOUBLE")
    payload = matrix["data"]
    if len(payload) != dims[0] * 8:
        raise MatError(f"{field}: payload {len(payload)} bytes != 8 * {dims[0]}")
    return bytes(payload), dims[0]


def field_rows(meas: dict, field: str) -> int:
    matrix = parse_matrix(meas["fields"][field])
    if matrix["empty"]:
        return 0
    dims = tuple(matrix["dims"])
    if len(dims) != 2:
        raise MatError(f"{field}: dims {dims} are not 2-D")
    return dims[0]


# --------------------------------------------------------------- validation

def analyze(path: Path) -> tuple[bytes, dict]:
    """Decode Voltage and Time, apply the shared acceptance rules, return stats."""
    meas = read_meas(path)
    names = meas["field_names"]
    for required in ("Voltage", "Current", "Time"):
        if required not in names:
            raise MatError(f"meas lacks {required}")
    if "TimeStamp" in names:
        stamp = parse_matrix(meas["fields"]["TimeStamp"])
        if stamp["class"] != MX_CELL:
            raise MatError("TimeStamp is not a cell array")
    voltage, count = double_column(meas, "Voltage")
    time_bytes, time_count = double_column(meas, "Time")
    if time_count != count:
        raise MatError(f"Time rows {time_count} != Voltage rows {count}")
    for name in names:
        if name != "TimeStamp" and field_rows(meas, name) != count:
            raise MatError(f"field {name} row count differs from Voltage")
    if count < MIN_VALUES_PER_FILE:
        raise MatError(f"only {count} Voltage rows")
    values = struct.unpack("<%dd" % count, voltage)
    if not all(math.isfinite(value) for value in values):
        raise MatError("Voltage contains non-finite values")
    v_lo, v_hi = min(values), max(values)
    if v_lo < V_MIN or v_hi > V_MAX:
        raise MatError(f"Voltage outside [{V_MIN}, {V_MAX}] V: {v_lo}..{v_hi}")
    distinct = len(set(voltage[i:i + 8] for i in range(0, len(voltage), 8)))
    if distinct < MIN_DISTINCT_PER_FILE:
        raise MatError(f"Voltage has only {distinct} distinct values")
    times = struct.unpack("<%dd" % count, time_bytes)
    if not all(math.isfinite(value) for value in times):
        raise MatError("Time contains non-finite values")
    steps = [times[i + 1] - times[i] for i in range(count - 1)]
    if min(steps) < 0:
        raise MatError("Time is not non-decreasing")
    nominal = sum(1 for step in steps if abs(step - NOMINAL_DT) <= NOMINAL_TOL)
    median_dt = statistics.median(steps)
    nominal_fraction = nominal / len(steps)
    if not MEDIAN_DT_RANGE[0] <= median_dt <= MEDIAN_DT_RANGE[1]:
        raise MatError(f"median Time step {median_dt:.6f} s is not ~0.1 s")
    if nominal_fraction < MIN_NOMINAL_FRACTION:
        raise MatError(f"only {nominal_fraction:.4f} of Time steps are ~0.1 s")
    five_decimal = sum(1 for value in values if float("%.5f" % value) == value)
    stats = {
        "value_count": count,
        "min": v_lo,
        "max": v_hi,
        "distinct_values": distinct,
        "five_decimal_exact_values": five_decimal,
        "duration_s": round(times[-1] - times[0], 3),
        "median_dt_s": round(median_dt, 6),
        "nominal_step_count": nominal,
        "off_nominal_step_count": len(steps) - nominal,
        "long_steps_over_10s": sum(1 for step in steps if step > 10.0),
        "fields": names,
    }
    return voltage, stats


# ------------------------------------------------------------ recipe tables

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_selection(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    expected_cols = ["seq", "sample_id", "ambient_condition", "profile", "test_start_local", "repo_path", "size_bytes", "sha256"]
    if not rows or list(rows[0].keys()) != expected_cols:
        raise SystemExit("selection.tsv schema changed")
    if len(rows) != EXPECTED_SELECTED:
        raise SystemExit(f"selection.tsv has {len(rows)} rows, expected {EXPECTED_SELECTED}")
    ids = set()
    for position, row in enumerate(rows, 1):
        row["seq"] = int(row["seq"])
        row["size_bytes"] = int(row["size_bytes"])
        if row["seq"] != position:
            raise SystemExit("selection.tsv seq order broken")
        if not re.fullmatch(r"[A-Za-z0-9_]+", row["sample_id"]) or row["sample_id"] in ids:
            raise SystemExit(f"bad or duplicate sample_id {row['sample_id']!r}")
        ids.add(row["sample_id"])
        if row["profile"] not in PROFILES or row["ambient_condition"] not in AMBIENTS:
            raise SystemExit(f"unexpected profile/ambient in {row['sample_id']}")
        if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise SystemExit(f"bad sha256 for {row['sample_id']}")
        if not row["repo_path"].startswith(REPO_ROOT_PREFIX) or not re.fullmatch(r"[A-Za-z0-9 ._/-]+\.mat", row["repo_path"]):
            raise SystemExit(f"bad repo_path {row['repo_path']!r}")
        base = row["repo_path"].rsplit("/", 1)[1]
        if not base.endswith(f" {row['sample_id']}_Pan18650PF.mat"):
            raise SystemExit(f"sample_id {row['sample_id']} does not match file name {base!r}")
        if not row["sample_id"].endswith("_" + row["profile"]):
            raise SystemExit(f"sample_id {row['sample_id']} does not end with profile {row['profile']}")
    if sum(row["size_bytes"] for row in rows) != EXPECTED_SOURCE_BYTES:
        raise SystemExit("selection.tsv source byte total changed")
    return rows


def load_excluded(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_EXCLUDED or list(rows[0].keys()) != ["repo_path", "size_bytes", "reason"]:
        raise SystemExit("excluded.tsv count or schema changed")
    for row in rows:
        if row["reason"] not in {"contiguous_multi_profile_log", "charge_or_pause_segment"}:
            raise SystemExit(f"unexpected exclusion reason {row['reason']!r}")
    return rows


def local_source(files_dir: Path, row: dict) -> Path:
    return files_dir / f"{row['sample_id']}.mat"


# ---------------------------------------------------------------- preflight

def check_evidence(downloads: Path) -> None:
    for key, (name, size, digest) in EVIDENCE.items():
        path = downloads / name
        if not path.is_file() or path.stat().st_size != size or file_sha256(path) != digest:
            raise SystemExit(f"evidence file identity mismatch: {name}")
    card = (downloads / EVIDENCE["mirror_readme"][0]).read_text(encoding="utf-8")
    for needle in ("10.17632/wykht8y7tg.1", "https://data.mendeley.com/datasets/wykht8y7tg/1", "**License** : CC-BY-4.0", "Kollmeyer, P. (2018)"):
        if needle not in card:
            raise SystemExit(f"mirror card lacks expected text: {needle!r}")
    readme = (downloads / EVIDENCE["upstream_readme"][0]).read_text(encoding="utf-8")
    for needle in (
        "If this data is utilized for any purpose, it should be appropriately referenced.",
        "drive cycles, were saved with a 0.1 second time step",
        "Voltage (measured cell terminal voltage",
        "some drive cycle data is included twice",
    ):
        if needle not in readme:
            raise SystemExit(f"upstream readme lacks expected text: {needle!r}")


def check_tree(tree_path: Path, selection: list[dict], excluded: list[dict]) -> None:
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    if not isinstance(tree, list):
        raise SystemExit("mirror tree listing is not a JSON list")
    files = {entry["path"]: entry for entry in tree if entry.get("type") == "file"}
    for row in selection:
        entry = files.get(row["repo_path"])
        if entry is None:
            raise SystemExit(f"selected file missing from mirror tree: {row['repo_path']}")
        oid = (entry.get("lfs") or {}).get("oid")
        if int(entry.get("size", -1)) != row["size_bytes"] or oid != row["sha256"]:
            raise SystemExit(f"mirror tree size/oid disagrees for {row['repo_path']}")
    excluded_paths = {row["repo_path"] for row in excluded}
    for row in excluded:
        entry = files.get(row["repo_path"])
        if entry is None or int(entry.get("size", -1)) != int(row["size_bytes"]):
            raise SystemExit(f"excluded file missing or resized in mirror tree: {row['repo_path']}")
    selected_paths = {row["repo_path"] for row in selection}
    covered = set()
    for path in files:
        if not path.startswith(REPO_ROOT_PREFIX) or not path.endswith(".mat"):
            continue
        folder = path[len(REPO_ROOT_PREFIX):].rpartition("/")[0]
        if folder in COVERED_FOLDERS:
            covered.add(path)
    unaccounted = covered - selected_paths - excluded_paths
    if unaccounted or selected_paths & excluded_paths:
        raise SystemExit(f"drive-cycle folder coverage changed: {sorted(unaccounted)[:5]}")
    print(f"mirror tree ok: {len(selected_paths)} selected + {len(excluded_paths)} excluded of {len(covered)} .mat files in covered folders")


def cmd_preflight(args: argparse.Namespace) -> None:
    selection = load_selection(args.selection)
    excluded = load_excluded(args.excluded)
    check_evidence(args.downloads)
    check_tree(args.downloads / TREE_NAME, selection, excluded)
    total = 0
    for row in selection:
        path = local_source(args.downloads / "files", row)
        if not path.is_file() or path.stat().st_size != row["size_bytes"] or file_sha256(path) != row["sha256"]:
            raise SystemExit(f"source identity mismatch: {path.name}")
        try:
            _, stats = analyze(path)
        except MatError as error:
            raise SystemExit(f"{path.name}: {error}") from error
        total += stats["value_count"]
        print(f"preflight ok {row['sample_id']} n={stats['value_count']} V={stats['min']}..{stats['max']} median_dt={stats['median_dt_s']}")
    print(f"preflight ok: {len(selection)} files, {total} Voltage values")


# -------------------------------------------------------------- build/verify

def index_row(row: dict, stats: dict, sample_rel: str, digest: str) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": sample_rel,
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": stats["value_count"] * 8,
        "value_count": stats["value_count"],
        "sha256": digest,
        "seq": row["seq"],
        "sample_id": row["sample_id"],
        "ambient_condition": row["ambient_condition"],
        "profile": row["profile"],
        "test_start_local": row["test_start_local"],
        "source_path": row["repo_path"],
        "source_sha256": row["sha256"],
        "min": stats["min"],
        "max": stats["max"],
        "distinct_values": stats["distinct_values"],
        "duration_s": stats["duration_s"],
        "median_dt_s": stats["median_dt_s"],
        "off_nominal_step_count": stats["off_nominal_step_count"],
        "long_steps_over_10s": stats["long_steps_over_10s"],
    }


def summarize(rows: list[dict], per_file: list[dict]) -> dict:
    counts = sorted(row["value_count"] for row in rows)
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "mirror_revision": REVISION,
        "sample_count": len(rows),
        "total_values": sum(counts),
        "total_bytes": sum(row["sample_size_bytes"] for row in rows),
        "median_values": statistics.median(counts),
        "min_values": counts[0],
        "max_values": counts[-1],
        "global_min_v": min(row["min"] for row in rows),
        "global_max_v": max(row["max"] for row in rows),
        "five_decimal_exact_values": sum(item["five_decimal_exact_values"] for item in per_file),
        "off_nominal_steps": sum(item["off_nominal_step_count"] for item in per_file),
        "files_with_long_steps": sum(1 for item in per_file if item["long_steps_over_10s"]),
        "per_ambient_samples": {
            ambient: sum(1 for row in rows if row["ambient_condition"] == ambient) for ambient in sorted(AMBIENTS)
        },
    }


def cmd_build(args: argparse.Namespace) -> None:
    selection = load_selection(args.selection)
    files_dir = args.downloads / "files"
    series_dir = args.samples_dir / SERIES_ID
    if args.samples_dir.exists():
        for stale in sorted(args.samples_dir.rglob("*"), reverse=True):
            if stale.is_file():
                stale.unlink()
            else:
                stale.rmdir()
    series_dir.mkdir(parents=True, exist_ok=True)
    rows, per_file = [], []
    for row in selection:
        source = local_source(files_dir, row)
        if not source.is_file() or source.stat().st_size != row["size_bytes"] or file_sha256(source) != row["sha256"]:
            raise SystemExit(f"source identity mismatch: {source}")
        try:
            voltage, stats = analyze(source)
        except MatError as error:
            raise SystemExit(f"{source.name}: {error}") from error
        target = series_dir / f"{row['seq']:02d}_{row['sample_id']}.bin"
        target.write_bytes(voltage)
        digest = hashlib.sha256(voltage).hexdigest()
        rows.append(index_row(row, stats, target.relative_to(args.data_root).as_posix(), digest))
        per_file.append(stats)
        print(f"wrote {target.name} values={stats['value_count']} V={stats['min']}..{stats['max']} distinct={stats['distinct_values']} off_nominal_steps={stats['off_nominal_step_count']}")
    if len({row["sha256"] for row in rows}) != len(rows):
        raise SystemExit("duplicate Voltage samples")
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    summary = summarize(rows, per_file)
    if summary["total_values"] != EXPECTED_TOTAL_VALUES:
        raise SystemExit(f"realized value total {summary['total_values']} != pinned {EXPECTED_TOTAL_VALUES}")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


def cmd_verify(args: argparse.Namespace) -> None:
    selection = load_selection(args.selection)
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [item for item in manifest["series"] if item["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        raise SystemExit("manifest primary series missing")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(selection):
        raise SystemExit(f"index has {len(rows)} rows, expected {len(selection)}")
    series_dir = args.samples_dir / SERIES_ID
    expected_names = {f"{row['seq']:02d}_{row['sample_id']}.bin" for row in selection}
    actual_names = {path.name for path in args.samples_dir.rglob("*") if path.is_file()}
    if actual_names != expected_names:
        raise SystemExit(f"sample directory mismatch: extra={sorted(actual_names - expected_names)[:3]} missing={sorted(expected_names - actual_names)[:3]}")
    digests = set()
    per_file = []
    for row, sel in zip(rows, selection):
        source = local_source(args.downloads / "files", sel)
        if file_sha256(source) != sel["sha256"]:
            raise SystemExit(f"source identity mismatch: {source}")
        try:
            voltage, stats = analyze(source)
        except MatError as error:
            raise SystemExit(f"{source.name}: {error}") from error
        sample = series_dir / f"{sel['seq']:02d}_{sel['sample_id']}.bin"
        data = sample.read_bytes()
        if data != voltage:
            raise SystemExit(f"{sample.name}: bytes differ from re-decoded source Voltage")
        expected = index_row(sel, stats, sample.relative_to(args.data_root).as_posix(), hashlib.sha256(data).hexdigest())
        if row != expected:
            diff = sorted(key for key in set(row) | set(expected) if row.get(key) != expected.get(key))
            raise SystemExit(f"{sample.name}: index row disagrees on {diff}")
        values = struct.unpack("<%dd" % (len(data) // 8), data)
        stored_min, stored_max = min(values), max(values)
        if stored_min != row["min"] or stored_max != row["max"] or stored_min == stored_max:
            raise SystemExit(f"{sample.name}: stored min/max mismatch or constant")
        if not all(V_MIN <= value <= V_MAX for value in values):
            raise SystemExit(f"{sample.name}: stored value outside voltage window")
        digests.add(row["sha256"])
        per_file.append(stats)
    if len(digests) != len(rows):
        raise SystemExit("duplicate samples")
    summary = summarize(rows, per_file)
    stored = json.loads(args.stats.read_text(encoding="utf-8"))
    if stored != json.loads(json.dumps(summary, sort_keys=True)):
        raise SystemExit("ingest_stats.json disagrees with re-derived summary")
    if series[0]["sample_count"] != summary["sample_count"] or series[0]["total_size_bytes"] != summary["total_bytes"]:
        raise SystemExit(
            f"manifest sample_count/total_size_bytes {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
            f"!= realized {summary['sample_count']}/{summary['total_bytes']}"
        )
    if summary["total_values"] != EXPECTED_TOTAL_VALUES:
        raise SystemExit(f"realized value total {summary['total_values']} != pinned {EXPECTED_TOTAL_VALUES}")
    if summary["median_values"] < 1_000 or summary["total_values"] < 10_000:
        raise SystemExit("primary floor not met")
    print(json.dumps(summary, sort_keys=True))
    print(f"verify ok: {summary['sample_count']} samples, {summary['total_values']} values, {summary['total_bytes']} bytes")


# ----------------------------------------------------------------- selftest

def _tag(element_type: int, payload: bytes, *, allow_small: bool = True) -> bytes:
    if allow_small and 0 < len(payload) <= 4:
        return struct.pack("<I", (len(payload) << 16) | element_type) + payload.ljust(4, b"\0")
    padded = payload + b"\0" * ((8 - len(payload) % 8) % 8)
    return struct.pack("<II", element_type, len(payload)) + padded


def _matrix(mx_class: int, dims: tuple[int, ...], name: str, body: bytes, flags_extra: int = 0) -> bytes:
    content = (
        _tag(MI_UINT32, struct.pack("<II", mx_class | flags_extra, 0), allow_small=False)
        + _tag(MI_INT32, struct.pack("<%di" % len(dims), *dims), allow_small=False)
        + _tag(MI_INT8, name.encode("ascii"))
        + body
    )
    return _tag(MI_MATRIX, content, allow_small=False)


def _double(values: list[float], name: str = "") -> bytes:
    return _matrix(MX_DOUBLE, (len(values), 1), name, _tag(MI_DOUBLE, struct.pack("<%dd" % len(values), *values), allow_small=False))


def _uint8_as_double(values: list[int]) -> bytes:
    return _matrix(MX_DOUBLE, (len(values), 1), "", _tag(MI_UINT8, bytes(values), allow_small=False))


def _char(text: str) -> bytes:
    return _matrix(MX_CHAR, (1, len(text)), "", _tag(MI_UTF8, text.encode("ascii")))


def _struct(name: str, fields: list[tuple[str, bytes]]) -> bytes:
    name_len = 32
    names = b"".join(field.encode("ascii").ljust(name_len, b"\0") for field, _ in fields)
    body = _tag(MI_INT32, struct.pack("<i", name_len)) + _tag(MI_INT8, names, allow_small=False)
    body += b"".join(payload for _, payload in fields)
    return _matrix(MX_STRUCT, (1, 1), name, body)


def _mat_file(elements: list[bytes]) -> bytes:
    header = b"MATLAB 5.0 MAT-file, Platform: PCWIN64, Created on: selftest".ljust(116, b" ")
    header += b"\0" * 8 + struct.pack("<H2s", 0x0100, b"IM")
    return header + b"".join(elements)


def _compressed(matrix: bytes) -> bytes:
    blob = zlib.compress(matrix)
    return struct.pack("<II", MI_COMPRESSED, len(blob)) + blob  # top-level: unpadded


def _synthetic(n: int, *, voltage_override=None, complex_voltage=False, dt: float = 0.1) -> tuple[bytes, list[float]]:
    times = [60.0 * i for i in range(20)]
    base = times[-1]
    times += [base + dt * (i + 1) for i in range(n - 20)]
    voltage = [round(4.18 - 0.00064 * (i % 1500) - 0.0001 * (i % 7), 5) for i in range(n)]
    if voltage_override:
        voltage_override(voltage)
    stamps = b"".join(_char(f"6/11/2017 1:{i % 60:02d}:00 PM") for i in range(n))
    stamp_cell = _matrix(MX_CELL, (n, 1), "", stamps)
    if complex_voltage:
        payload = struct.pack("<%dd" % n, *voltage)
        volt = _matrix(MX_DOUBLE, (n, 1), "", _tag(MI_DOUBLE, payload, allow_small=False) * 2, flags_extra=FLAG_COMPLEX)
    else:
        volt = _double(voltage)
    meas = _struct("meas", [
        ("TimeStamp", stamp_cell),
        ("Voltage", volt),
        ("Current", _double([(-1.0) ** i * 0.5 for i in range(n)])),
        ("Ah", _double([-0.001 * i for i in range(n)])),
        ("Wh", _double([float("nan")] * n)),
        ("Power", _double([1.5] * n)),
        ("Battery_Temp_degC", _double([25.0 + 0.01 * i for i in range(n)])),
        ("Time", _double(times)),
        ("Chamber_Temp_degC", _uint8_as_double([25] * n)),
    ])
    other = _double([1.0, 2.0, 3.0], "x")  # a second, uncompressed top-level variable
    raw = _mat_file([_compressed(meas), other])
    return raw, voltage


def cmd_selftest(_: argparse.Namespace) -> None:
    with tempfile.TemporaryDirectory(prefix="kollmeyer_selftest_") as tmp:
        tmpdir = Path(tmp)
        good, expected = _synthetic(3_000)
        path = tmpdir / "good.mat"
        path.write_bytes(good)
        voltage, stats = analyze(path)
        assert voltage == struct.pack("<%dd" % len(expected), *expected), "Voltage bytes differ"
        assert stats["value_count"] == 3_000 and stats["long_steps_over_10s"] == 19, stats
        assert stats["five_decimal_exact_values"] == 3_000, stats
        meas = read_meas(path)
        assert meas["field_names"][0] == "TimeStamp" and parse_matrix(meas["fields"]["TimeStamp"])["cell_count"] == 3_000
        failures = {
            "range": dict(voltage_override=lambda v: v.__setitem__(5, 4.5)),
            "nan": dict(voltage_override=lambda v: v.__setitem__(5, float("nan"))),
            "complex": dict(complex_voltage=True),
            "slow_cadence": dict(dt=1.0),
            "constant": dict(voltage_override=lambda v: v.__setitem__(slice(None), [3.7] * len(v))),
        }
        for label, kwargs in failures.items():
            bad, _ = _synthetic(3_000, **kwargs)
            bad_path = tmpdir / f"{label}.mat"
            bad_path.write_bytes(bad)
            try:
                analyze(bad_path)
            except MatError:
                continue
            raise AssertionError(f"selftest: {label} file was accepted")
        truncated = tmpdir / "truncated.mat"
        truncated.write_bytes(good[:-40])
        try:
            analyze(truncated)
        except (MatError, struct.error):
            pass
        else:
            raise AssertionError("selftest: truncated file was accepted")
        trailing = tmpdir / "trailing.mat"
        blob_start = 128 + 8
        blob_len = struct.unpack_from("<I", good, 132)[0]
        tampered = bytearray(good)
        tampered[132:136] = struct.pack("<I", blob_len + 8)
        trailing.write_bytes(bytes(tampered[:blob_start + blob_len]) + b"\x01" * 8 + bytes(tampered[blob_start + blob_len:]))
        try:
            analyze(trailing)
        except MatError:
            pass
        else:
            raise AssertionError("selftest: zlib stream with trailing bytes was accepted")
    print(
        "selftest ok: synthetic MAT v5 (packed small elements, struct field names, cell TimeStamp, "
        "uint8-stored double, compressed + uncompressed variables) decoded byte-exactly; "
        "range/NaN/complex/slow-cadence/constant/truncated/trailing-zlib inputs rejected"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest")
    for name in ("preflight", "build", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--selection", type=Path, required=True)
        command.add_argument("--downloads", type=Path, required=True)
        if name == "preflight":
            command.add_argument("--excluded", type=Path, required=True)
        else:
            command.add_argument("--samples-dir", type=Path, required=True)
            command.add_argument("--index", type=Path, required=True)
            command.add_argument("--stats", type=Path, required=True)
            command.add_argument("--data-root", type=Path, required=True)
        if name == "verify":
            command.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    {"selftest": cmd_selftest, "preflight": cmd_preflight, "build": cmd_build, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
