#!/usr/bin/env python3
"""AfSIS Phase I soil MIR absorbance spectra -> one little-endian float32
sample per soil-sample spectrum.

Subcommands:
  check-listing  validate the pinned Dataverse version-1.1 JSON listing
  check-file     semantic check of one downloaded country CSV (header grid)
  build          emit samples, index, and ingest statistics from local files
  verify         independently re-derive and check the built output
  selftest       exercise the parsers and the lattice argument on synthetic data

Pure standard library. Network I/O lives in download.sh (curl), never here.
"""
from __future__ import annotations

import argparse
import array
import csv
import decimal
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import statistics
import struct
import sys
import tempfile


DATASET_ID = "icraf_afsis1_soil_mir_spectra_f32"
SERIES_ID = "afsis1_soil_mir_absorbance_f32"
NATURAL_RECORD_KIND = "afsis1_soil_sample_mir_absorbance_spectrum"
PERSISTENT_ID = "doi:10.34725/DVN/QXCWP1"
DISCLAIMER_FILE_ID = 10842

# All 19 country CSVs share this byte-identical header line (probed 2026-10-05):
# Num,SSN,Depth,Country,m4001.6,m3999.7,...,m2381.7,m2350.8,...,m601.7
HEADER_SHA256 = "570c81aa54a569adea4c11b444c4861758296f283e06f77c95c3e0023b830d11"
HEADER_BYTES = 13456
BOOKKEEPING_COLUMNS = ("Num", "SSN", "Depth", "Country")
N_SPECTRAL = 1749
N_COLUMNS = len(BOOKKEEPING_COLUMNS) + N_SPECTRAL
FIRST_LABEL = "m4001.6"
LAST_LABEL = "m601.7"
CO2_GAP = ("m2381.7", "m2350.8")
DEPTHS = frozenset({"Topsoil", "Subsoil"})
SSN_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
NUM_RE = re.compile(r"[0-9]{1,7}")

# Source decimals carry at most 8 fractional digits and sit on a 2.5e-7 lattice
# (4-replicate means of 6-decimal values). LATTICE_PER_UNIT = 1 / 2.5e-7.
LATTICE_PER_UNIT = 4_000_000
# |value| < 4  <=>  |q| < 16,000,000 < 2**24: binary32 half-ulp (<= 2**-23)
# stays below half the lattice step (1.25e-7), so round(f32 * 4e6) == q.
LATTICE_ABS_LIMIT = 16_000_000
DEC_RE = re.compile(r"(-?)([0-9]+)(?:\.([0-9]+))?")
MIN_DISTINCT_PER_SAMPLE = 100

# Rows excluded from the primary series. Each class is re-derived by rule in
# both build and verify and must then equal the pinned SSN set exactly.
# (a) Placeholder rows whose 1,749 spectral cells are all the literal "NA":
#     no spectrum was recorded for these samples.
NO_SPECTRUM_SSNS = frozenset({
    "icr075150", "icr075279",  # Botswana
    "icr015372", "icr069796",  # Mali
    "icr024965",  # Tanzania
    "icr075956",  # Zambia
    "icr075550",  # Zimbabwe ("Zimbambwe")
})
# (b) Rows whose every cell is k / 3e6 printed to 9 decimals (3-replicate means
#     of 6-decimal readings): a different tick lattice from the 2.5e-7 lattice
#     of every other spectrum, so they are kept out of the family.
THREE_REPLICATE_SSNS = frozenset({
    "icr033584",  # Kenya
    "icr037556",  # Mali
    "icr075955",  # Zambia
})

INDEX_BASE = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "role": "primary",
    "numeric_kind": "float",
    "bit_width": 32,
    "endianness": "little",
    "element_size_bytes": 4,
    "sample_size_bytes": N_SPECTRAL * 4,
    "value_count": N_SPECTRAL,
    "shape": [N_SPECTRAL],
    "natural_record_kind": NATURAL_RECORD_KIND,
}

_header_sha256 = HEADER_SHA256  # overridden only by selftest
_no_spectrum_ssns = NO_SPECTRUM_SSNS  # overridden only by selftest
_three_replicate_ssns = THREE_REPLICATE_SSNS  # overridden only by selftest


class RecipeError(ValueError):
    pass


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def load_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    expected = [
        "datafile_id",
        "local_filename",
        "upstream_ingested_name",
        "country_column_value",
        "original_size_bytes",
        "original_md5",
    ]
    if header != expected:
        raise RecipeError(f"unexpected sources.tsv header {header}")
    sources = []
    for line in lines[1:]:
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != len(expected):
            raise RecipeError(f"bad sources.tsv line {line!r}")
        row = dict(zip(expected, parts))
        row["datafile_id"] = int(row["datafile_id"])
        row["original_size_bytes"] = int(row["original_size_bytes"])
        sources.append(row)
    ids = [row["datafile_id"] for row in sources]
    if ids != sorted(set(ids)):
        raise RecipeError("sources.tsv datafile ids must be unique and ascending")
    return sources


def file_digests(path: Path) -> tuple[int, str, str]:
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            size += len(chunk)
            md5.update(chunk)
            sha.update(chunk)
    return size, md5.hexdigest(), sha.hexdigest()


def validate_source_file(path: Path, source: dict) -> str:
    if not path.is_file():
        raise RecipeError(f"missing source CSV {path}")
    size, md5, sha = file_digests(path)
    if size != source["original_size_bytes"] or md5 != source["original_md5"]:
        raise RecipeError(
            f"{path.name}: identity mismatch size={size} md5={md5}, expected "
            f"size={source['original_size_bytes']} md5={source['original_md5']}"
        )
    return sha


def header_labels_ok(header_line: str) -> list[str]:
    digest = hashlib.sha256(header_line.encode("ascii")).hexdigest()
    if digest != _header_sha256:
        raise RecipeError(f"header line SHA-256 {digest} != pinned {_header_sha256}")
    cols = header_line.split(",")
    if len(cols) != N_COLUMNS or tuple(cols[:4]) != BOOKKEEPING_COLUMNS:
        raise RecipeError(f"header has {len(cols)} columns / prefix {cols[:4]}")
    labels = cols[4:]
    if _header_sha256 == HEADER_SHA256 and (labels[0] != FIRST_LABEL or labels[-1] != LAST_LABEL):
        raise RecipeError("spectral grid endpoints differ from m4001.6..m601.7")
    wavenumbers = [float(label[1:]) for label in labels]
    if any(not label.startswith("m") for label in labels) or any(
        a <= b for a, b in zip(wavenumbers, wavenumbers[1:])
    ):
        raise RecipeError("spectral labels are not strictly decreasing m<wavenumber> labels")
    return labels


def lattice_int(text: str) -> tuple[int, int]:
    """Exact integer q with value == q * 2.5e-7, plus the printed decimal count."""
    match = DEC_RE.fullmatch(text)
    if match is None:
        raise RecipeError(f"non-decimal spectral cell {text!r}")
    sign, whole, frac = match.groups()
    frac = frac or ""
    if len(frac) > 8:
        if frac[8:].strip("0"):
            raise RecipeError(f"cell {text!r} has more than 8 significant fractional digits")
        frac = frac[:8]
    units = int(whole + frac.ljust(8, "0"))  # value in 1e-8
    if units % 25:
        raise RecipeError(f"cell {text!r} is off the 2.5e-7 lattice")
    q = units // 25
    if q >= LATTICE_ABS_LIMIT:
        raise RecipeError(f"cell {text!r}: |absorbance| >= 4, binary32 cannot hold the 2.5e-7 lattice")
    return (-q if sign else q), len(frac)


def check_exclusions(no_spectrum: list[dict], three_replicate: list[dict]) -> None:
    observed_na = {item["ssn"] for item in no_spectrum}
    observed_three = {item["ssn"] for item in three_replicate}
    if observed_na != _no_spectrum_ssns or len(no_spectrum) != len(observed_na):
        raise RecipeError(f"all-NA rows {sorted(observed_na)} != pinned {sorted(_no_spectrum_ssns)}")
    if observed_three != _three_replicate_ssns or len(three_replicate) != len(observed_three):
        raise RecipeError(
            f"3-replicate-lattice rows {sorted(observed_three)} != pinned {sorted(_three_replicate_ssns)}"
        )


def relative_to(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise RecipeError(f"{path} is outside {root}") from exc


def f32_round_trip(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


# --------------------------------------------------------------------------
# download-time checks
# --------------------------------------------------------------------------

def check_listing(args: argparse.Namespace) -> None:
    sources = load_sources(args.sources)
    payload = json.loads(args.json.read_text(encoding="utf-8"))
    if payload.get("status") != "OK":
        raise RecipeError(f"listing status {payload.get('status')!r}")
    data = payload["data"]
    if data.get("datasetPersistentId") != PERSISTENT_ID:
        raise RecipeError(f"persistent id {data.get('datasetPersistentId')!r}")
    if (data.get("versionNumber"), data.get("versionMinorNumber"), data.get("versionState")) != (1, 1, "RELEASED"):
        raise RecipeError("listing is not released version 1.1")
    terms = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", data.get("termsOfUse", ""))))
    for needle in (
        "Creative Commons Attribution 4.0 International license (CC-BY-4.0)",
        "for any purpose, even commercially",
    ):
        if needle not in terms:
            raise RecipeError(f"termsOfUse lacks {needle!r}")
    if "creativecommons.org/licenses/by/4.0" not in data.get("termsOfUse", ""):
        raise RecipeError("termsOfUse lacks the CC BY 4.0 link")
    files = {entry["dataFile"]["id"]: entry["dataFile"] for entry in data["files"]}
    expected_ids = {row["datafile_id"] for row in sources} | {DISCLAIMER_FILE_ID}
    if set(files) != expected_ids:
        raise RecipeError(f"listing file ids {sorted(files)} != expected {sorted(expected_ids)}")
    for row in sources:
        entry = files[row["datafile_id"]]
        observed = (
            entry.get("filename"),
            entry.get("originalFileSize"),
            entry.get("md5"),
            entry.get("originalFileFormat"),
        )
        expected = (row["upstream_ingested_name"], row["original_size_bytes"], row["original_md5"], "text/csv")
        if observed != expected:
            raise RecipeError(f"datafile {row['datafile_id']}: listing {observed} != pinned {expected}")
    print(f"listing_ok version=1.1 files={len(sources)} license=CC-BY-4.0 "
          f"bytes={sum(row['original_size_bytes'] for row in sources)}")


def check_file(args: argparse.Namespace) -> None:
    raw = args.path.read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RecipeError(f"{args.path.name}: non-ASCII content") from exc
    header, sep, rest = text.partition("\r\n")
    if not sep:
        raise RecipeError(f"{args.path.name}: no CRLF-terminated header line")
    header_labels_ok(header)
    rows = [line for line in rest.split("\r\n") if line]
    if not rows:
        raise RecipeError(f"{args.path.name}: no data rows")
    for number, line in enumerate(rows, 1):
        if line.count(",") != N_COLUMNS - 1:
            raise RecipeError(f"{args.path.name}: data row {number} has {line.count(',') + 1} columns")
        if line.split(",", 4)[3] != args.country:
            raise RecipeError(f"{args.path.name}: data row {number} Country is not {args.country!r}")
    print(f"file_ok name={args.path.name} rows={len(rows)} header_sha256={_header_sha256}")


# --------------------------------------------------------------------------
# build (parse path A: plain CRLF/comma split + exact integer lattice parse)
# --------------------------------------------------------------------------

def iter_rows_split(path: Path, country: str):
    text = path.read_bytes().decode("ascii")
    if '"' in text:
        raise RecipeError(f"{path.name}: quoted CSV fields are not expected")
    if text.endswith("\r\n"):
        text = text[:-2]
    lines = text.split("\r\n")
    if any("\n" in line or "\r" in line for line in lines):
        raise RecipeError(f"{path.name}: mixed line endings")
    labels = header_labels_ok(lines[0])
    rows = []
    for row_number, line in enumerate(lines[1:], 1):
        fields = line.split(",")
        if len(fields) != N_COLUMNS:
            raise RecipeError(f"{path.name} row {row_number}: {len(fields)} columns")
        num, ssn, depth, row_country = fields[:4]
        if not NUM_RE.fullmatch(num):
            raise RecipeError(f"{path.name} row {row_number}: bad Num {num!r}")
        if not SSN_RE.fullmatch(ssn):
            raise RecipeError(f"{path.name} row {row_number}: bad SSN {ssn!r}")
        if depth not in DEPTHS:
            raise RecipeError(f"{path.name} row {row_number}: Depth {depth!r} not Topsoil/Subsoil")
        if row_country != country:
            raise RecipeError(f"{path.name} row {row_number}: Country {row_country!r} != {country!r}")
        rows.append((row_number, int(num), ssn, depth, fields[4:]))
    return labels, rows


def is_three_replicate_row(cells: list[str]) -> bool:
    """Every cell equals k / 3e6 rounded half-up to 9 decimals; some cell has 9."""
    nine = 0
    for cell in cells:
        match = DEC_RE.fullmatch(cell)
        if match is None:
            return False
        _, whole, frac = match.groups()
        frac = frac or ""
        if len(frac) > 9:
            return False
        nine += len(frac) == 9
        units = int(whole + frac.ljust(9, "0"))  # |value| in 1e-9
        k = (3 * units + 500) // 1000  # nearest k with |value| ~ k / 3e6
        if (2000 * k + 3) // 6 != units:  # k / 3e6 rounded half-up to 1e-9
            return False
    return nine > 0


def convert_row(cells: list[str], context: str, decimals_hist: dict[int, int]) -> tuple[bytes, list[float], float]:
    lattice = []
    local_hist: dict[int, int] = {}
    for cell in cells:
        q, ndec = lattice_int(cell)
        lattice.append(q)
        local_hist[ndec] = local_hist.get(ndec, 0) + 1
    for ndec, count in local_hist.items():
        decimals_hist[ndec] = decimals_hist.get(ndec, 0) + count
    values64 = [float(cell) for cell in cells]
    if not all(math.isfinite(v) for v in values64):
        raise RecipeError(f"{context}: non-finite value")
    payload = struct.pack(f"<{N_SPECTRAL}f", *values64)
    stored = struct.unpack(f"<{N_SPECTRAL}f", payload)
    worst = 0.0
    for q, v32 in zip(lattice, stored):
        scaled = v32 * LATTICE_PER_UNIT  # exact in binary64
        if round(scaled) != q:
            raise RecipeError(f"{context}: float32 {v32!r} does not recover lattice integer {q}")
        worst = max(worst, abs(scaled - q))
    return payload, list(stored), worst


def build(args: argparse.Namespace) -> dict:
    sources = load_sources(args.sources)
    data_root = args.data_root.resolve()
    csv_dir = args.csv_dir.resolve()
    samples_root = args.samples_dir.resolve()
    output_dir = samples_root / SERIES_ID
    temporary_dir = samples_root / f".{SERIES_ID}.tmp"
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    temporary_dir.mkdir(parents=True)

    rows_out: list[dict] = []
    per_file: list[dict] = []
    duplicates: list[dict] = []
    excluded_no_spectrum: list[dict] = []
    excluded_three_replicate: list[dict] = []
    seen_ssn: dict[str, int] = {}
    seen_ssn_folded: set[str] = set()
    seen_payload: dict[str, str] = {}
    decimals_hist: dict[int, int] = {}
    aggregate = hashlib.sha256()
    grid: list[str] | None = None
    worst_lattice_error = 0.0
    depth_counts = {"Topsoil": 0, "Subsoil": 0}
    global_min = math.inf
    global_max = -math.inf
    try:
        for source in sources:
            path = csv_dir / source["local_filename"]
            source_sha = validate_source_file(path, source)
            labels, rows = iter_rows_split(path, source["country_column_value"])
            if grid is None:
                grid = labels
            elif labels != grid:
                raise RecipeError(f"{path.name}: wavenumber grid differs from first file")
            kept = 0
            for row_number, num, ssn, depth, cells in rows:
                context = f"{path.name} row {row_number} ({ssn})"
                if ssn in seen_ssn or ssn.lower() in seen_ssn_folded:
                    raise RecipeError(f"{context}: duplicate SSN (first in datafile {seen_ssn.get(ssn)})")
                seen_ssn[ssn] = source["datafile_id"]
                seen_ssn_folded.add(ssn.lower())
                record = {"ssn": ssn, "datafile_id": source["datafile_id"],
                          "source_row": row_number, "depth": depth}
                if all(cell == "NA" for cell in cells):
                    excluded_no_spectrum.append(record)
                    continue
                try:
                    payload, stored, worst = convert_row(cells, context, decimals_hist)
                except RecipeError:
                    if is_three_replicate_row(cells):
                        excluded_three_replicate.append(record)
                        continue
                    raise
                distinct = len(set(stored))
                if distinct < MIN_DISTINCT_PER_SAMPLE:
                    raise RecipeError(f"{context}: degenerate spectrum with {distinct} distinct values")
                digest = hashlib.sha256(payload).hexdigest()
                if digest in seen_payload:
                    duplicates.append({"ssn": ssn, "datafile_id": source["datafile_id"],
                                       "source_row": row_number, "duplicate_of_ssn": seen_payload[digest]})
                    continue
                seen_payload[digest] = ssn
                worst_lattice_error = max(worst_lattice_error, worst)
                filename = f"{ssn}.bin"
                (temporary_dir / filename).write_bytes(payload)
                aggregate.update(payload)
                low, high = min(stored), max(stored)
                global_min = min(global_min, low)
                global_max = max(global_max, high)
                depth_counts[depth] += 1
                row = dict(INDEX_BASE)
                row.update({
                    "sample_path": relative_to(output_dir / filename, data_root),
                    "min": low,
                    "max": high,
                    "distinct_values": distinct,
                    "sample_sha256": digest,
                    "ssn": ssn,
                    "depth": depth,
                    "country_column_value": source["country_column_value"],
                    "source_datafile_id": source["datafile_id"],
                    "source_row": row_number,
                    "source_num": num,
                })
                rows_out.append(row)
                kept += 1
            per_file.append({
                "datafile_id": source["datafile_id"],
                "local_filename": source["local_filename"],
                "upstream_ingested_name": source["upstream_ingested_name"],
                "source_sha256": source_sha,
                "rows": len(rows),
                "samples": kept,
            })
            print(f"parsed {path.name} rows={len(rows)} kept={kept} total={len(rows_out)}", flush=True)
        if not rows_out:
            raise RecipeError("no samples produced")
        check_exclusions(excluded_no_spectrum, excluded_three_replicate)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary_dir.replace(output_dir)
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise

    index_path = args.index.resolve()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows_out:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(index_path)

    total_values = len(rows_out) * N_SPECTRAL
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "dataverse_version": "1.1",
        "header_sha256": HEADER_SHA256,
        "wavenumber_labels_cm-1": grid,
        "files": per_file,
        "source_rows": sum(item["rows"] for item in per_file),
        "excluded_no_spectrum_rows": excluded_no_spectrum,
        "excluded_three_replicate_rows": excluded_three_replicate,
        "duplicate_spectra_dropped": duplicates,
        "sample_count": len(rows_out),
        "depth_counts": depth_counts,
        "total_values": total_values,
        "total_size_bytes": total_values * 4,
        "stored_min": global_min,
        "stored_max": global_max,
        "printed_fraction_digits_histogram": {str(k): v for k, v in sorted(decimals_hist.items())},
        "max_float32_error_in_lattice_steps": worst_lattice_error,
        "aggregate_payload_sha256": aggregate.hexdigest(),
    }
    stats_path = args.stats.resolve()
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = stats_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(stats_path)
    summary = {k: v for k, v in stats.items() if k not in {"wavenumber_labels_cm-1", "files"}}
    print(json.dumps(summary, indent=1, sort_keys=True))
    return stats


# --------------------------------------------------------------------------
# verify (parse path B: csv module + decimal.Decimal lattice + array packing)
# --------------------------------------------------------------------------

_DEC_CTX = decimal.Context(prec=40, traps=[decimal.InvalidOperation])
_LATTICE_D = decimal.Decimal(LATTICE_PER_UNIT)
_PLAIN_DECIMAL_CHARS = frozenset("-.0123456789")


def decimal_lattice(text: str, context: str) -> int:
    if not text or not set(text) <= _PLAIN_DECIMAL_CHARS:
        raise RecipeError(f"{context}: cell {text!r} is not a plain decimal")
    try:
        value = _DEC_CTX.create_decimal(text)
    except decimal.InvalidOperation as exc:
        raise RecipeError(f"{context}: unparsable cell {text!r}") from exc
    if not value.is_finite():
        raise RecipeError(f"{context}: non-finite cell {text!r}")
    scaled = _DEC_CTX.multiply(value, _LATTICE_D)
    if scaled != scaled.to_integral_value():
        raise RecipeError(f"{context}: cell {text!r} is off the 2.5e-7 lattice")
    q = int(scaled)
    if abs(q) >= LATTICE_ABS_LIMIT:
        raise RecipeError(f"{context}: cell {text!r} has |absorbance| >= 4")
    return q


_THREE_E6 = decimal.Decimal(3_000_000)
_NANO = decimal.Decimal("1e-9")


def decimal_three_replicate(cells: list[str]) -> bool:
    nine = 0
    for cell in cells:
        if not cell or not set(cell) <= _PLAIN_DECIMAL_CHARS:
            return False
        try:
            value = _DEC_CTX.create_decimal(cell)
        except decimal.InvalidOperation:
            return False
        exponent = value.as_tuple().exponent
        if not value.is_finite() or exponent < -9:
            return False
        nine += exponent == -9
        k = _DEC_CTX.multiply(value, _THREE_E6).to_integral_value(rounding=decimal.ROUND_HALF_EVEN)
        reprinted = _DEC_CTX.divide(k, _THREE_E6).quantize(_NANO, rounding=decimal.ROUND_HALF_UP)
        if reprinted != value:
            return False
    return nine > 0


def pack_array(cells: list[str]) -> bytes:
    values = array.array("f", [float(cell) for cell in cells])
    if values.itemsize != 4:
        raise RecipeError("platform float is not 4 bytes")
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def verify(args: argparse.Namespace) -> None:
    import tomllib

    sources = load_sources(args.sources)
    data_root = args.data_root.resolve()
    csv_dir = args.csv_dir.resolve()
    output_dir = args.samples_dir.resolve() / SERIES_ID
    index_path = args.index.resolve()
    stats_path = args.stats.resolve()
    for required in (output_dir, index_path, stats_path):
        if not required.exists():
            raise RecipeError(f"missing build output {required}")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    by_ssn: dict[str, dict] = {}
    for row in index_rows:
        if row.get("ssn") in by_ssn:
            raise RecipeError(f"duplicate indexed SSN {row.get('ssn')}")
        by_ssn[row["ssn"]] = row

    expected_names: set[str] = set()
    seen_payload: dict[str, str] = {}
    duplicates: list[dict] = []
    excluded_no_spectrum: list[dict] = []
    excluded_three_replicate: list[dict] = []
    ordered_ssns: list[str] = []
    aggregate = hashlib.sha256()
    global_min = math.inf
    global_max = -math.inf
    grid = None
    source_rows = 0
    for source in sources:
        path = csv_dir / source["local_filename"]
        validate_source_file(path, source)
        with path.open("r", encoding="ascii", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader)
            if hashlib.sha256(",".join(header).encode("ascii")).hexdigest() != _header_sha256:
                raise RecipeError(f"{path.name}: header differs from the pinned grid")
            if grid is None:
                grid = header[4:]
            elif header[4:] != grid:
                raise RecipeError(f"{path.name}: grid differs")
            for row_number, fields in enumerate(reader, 1):
                source_rows += 1
                context = f"{path.name} row {row_number}"
                if len(fields) != N_COLUMNS or any(field == "" for field in fields):
                    raise RecipeError(f"{context}: wrong column count or empty cell")
                _, ssn, depth, country = fields[:4]
                if depth not in DEPTHS or country != source["country_column_value"]:
                    raise RecipeError(f"{context}: bad Depth/Country {depth!r}/{country!r}")
                cells = fields[4:]
                record = {"ssn": ssn, "datafile_id": source["datafile_id"],
                          "source_row": row_number, "depth": depth}
                if set(cells) == {"NA"}:
                    excluded_no_spectrum.append(record)
                    if ssn in by_ssn:
                        raise RecipeError(f"{context}: all-NA row {ssn} must not be indexed")
                    continue
                try:
                    lattice = [decimal_lattice(cell, context) for cell in cells]
                except RecipeError:
                    if not decimal_three_replicate(cells):
                        raise
                    excluded_three_replicate.append(record)
                    if ssn in by_ssn:
                        raise RecipeError(f"{context}: 3-replicate row {ssn} must not be indexed")
                    continue
                expected = pack_array(cells)
                digest = hashlib.sha256(expected).hexdigest()
                if digest in seen_payload:
                    if ssn in by_ssn:
                        raise RecipeError(f"{context}: duplicate spectrum {ssn} must not be indexed")
                    duplicates.append({"ssn": ssn, "datafile_id": source["datafile_id"],
                                       "source_row": row_number, "duplicate_of_ssn": seen_payload[digest]})
                    continue
                seen_payload[digest] = ssn
                row = by_ssn.get(ssn)
                if row is None:
                    raise RecipeError(f"{context}: spectrum {ssn} missing from index")
                sample = data_root / row["sample_path"]
                if sample != output_dir / f"{ssn}.bin":
                    raise RecipeError(f"{context}: unexpected sample path {row['sample_path']}")
                actual = sample.read_bytes()
                if actual != expected:
                    raise RecipeError(f"{context}: sample bytes differ from source conversion")
                stored = struct.unpack(f"<{N_SPECTRAL}f", actual)
                for q, v32 in zip(lattice, stored):
                    if round(v32 * LATTICE_PER_UNIT) != q:
                        raise RecipeError(f"{context}: stored float32 loses lattice integer {q}")
                low, high = min(stored), max(stored)
                distinct = len(set(stored))
                if low == high or distinct < MIN_DISTINCT_PER_SAMPLE:
                    raise RecipeError(f"{context}: degenerate spectrum")
                want = dict(INDEX_BASE)
                want.update({
                    "min": low,
                    "max": high,
                    "distinct_values": distinct,
                    "sample_sha256": digest,
                    "depth": depth,
                    "country_column_value": source["country_column_value"],
                    "source_datafile_id": source["datafile_id"],
                    "source_row": row_number,
                    "source_num": int(fields[0]),
                })
                for key, value in want.items():
                    if row.get(key) != value:
                        raise RecipeError(f"{context}: index field {key}={row.get(key)!r} != {value!r}")
                if row["sample_size_bytes"] != len(actual):
                    raise RecipeError(f"{context}: index size mismatch")
                aggregate.update(actual)
                global_min = min(global_min, low)
                global_max = max(global_max, high)
                expected_names.add(sample.name)
                ordered_ssns.append(ssn)
        print(f"verified {path.name} samples_so_far={len(ordered_ssns)}", flush=True)

    if ordered_ssns != [row["ssn"] for row in index_rows]:
        raise RecipeError("index rows are not exactly the re-derived spectra in source order")
    check_exclusions(excluded_no_spectrum, excluded_three_replicate)
    on_disk = set(os.listdir(output_dir))
    if on_disk != expected_names:
        extra = sorted(on_disk - expected_names)[:5]
        missing = sorted(expected_names - on_disk)[:5]
        raise RecipeError(f"sample directory mismatch extra={extra} missing={missing}")
    checks = {
        "sample_count": len(ordered_ssns),
        "total_size_bytes": len(ordered_ssns) * N_SPECTRAL * 4,
        "source_rows": source_rows,
        "excluded_no_spectrum_rows": excluded_no_spectrum,
        "excluded_three_replicate_rows": excluded_three_replicate,
        "duplicate_spectra_dropped": duplicates,
        "aggregate_payload_sha256": aggregate.hexdigest(),
        "stored_min": global_min,
        "stored_max": global_max,
        "wavenumber_labels_cm-1": grid,
    }
    for key, value in checks.items():
        if stats.get(key) != value:
            raise RecipeError(f"ingest stats {key} disagrees with re-derivation")
    if args.manifest is not None:
        manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
        series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
        if len(series) != 1:
            raise RecipeError("manifest must declare exactly one primary series")
        claimed = (series[0].get("sample_count"), series[0].get("total_size_bytes"))
        realized = (checks["sample_count"], checks["total_size_bytes"])
        if claimed != realized:
            raise RecipeError(f"manifest claims {claimed} but output realizes {realized}")
    print(json.dumps({k: v for k, v in checks.items() if k != "wavenumber_labels_cm-1"}, indent=1))
    print("verify_ok")


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------

def _lattice_text(q: int) -> str:
    sign = "-" if q < 0 else ""
    units = abs(q) * 25
    whole, frac = divmod(units, 100_000_000)
    frac_text = f"{frac:08d}".rstrip("0")
    return f"{sign}{whole}.{frac_text}" if frac_text else f"{sign}{whole}"


def _expect_failure(label: str, func) -> None:
    try:
        func()
    except RecipeError as exc:
        print(f"selftest expected_failure {label}: {exc}")
        return
    raise AssertionError(f"selftest: {label} did not fail")


def _three_replicate_text(k: int) -> str:
    value = (decimal.Decimal(k) / _THREE_E6).quantize(_NANO, rounding=decimal.ROUND_HALF_UP)
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def selftest(_: argparse.Namespace) -> None:
    global _header_sha256, _no_spectrum_ssns, _three_replicate_ssns
    rng = random.Random(20261005)

    # 1. lattice argument: text -> float64 -> float32 -> round(*4e6) recovers q
    windows = [range(0, 200_000), range(3_900_000, 4_100_000), range(7_900_000, 8_100_000),
               range(15_800_000, LATTICE_ABS_LIMIT)]
    checked = 0
    for window in windows:
        for q in window:
            for signed in (q, -q):
                text = _lattice_text(signed)
                assert lattice_int(text)[0] == signed
                assert round(f32_round_trip(float(text)) * LATTICE_PER_UNIT) == signed, text
                checked += 1
    for _ in range(500_000):
        q = rng.randrange(-LATTICE_ABS_LIMIT + 1, LATTICE_ABS_LIMIT)
        text = _lattice_text(q)
        assert lattice_int(text)[0] == q and decimal_lattice(text, "t") == q
        assert round(f32_round_trip(float(text)) * LATTICE_PER_UNIT) == q, text
        checked += 1
    lost = sum(
        round(f32_round_trip(float(_lattice_text(q))) * LATTICE_PER_UNIT) != q
        for q in range(LATTICE_ABS_LIMIT, LATTICE_ABS_LIMIT + 10_000)
    )
    assert lost > 0, "expected lattice loss above |x| = 4"
    print(f"selftest lattice_ok checked={checked} lost_just_above_4={lost}/10000")
    for good, q in (("0.51261275", 2050451), ("1.7889435", 7155774), ("0.513102", 2052408),
                    ("2", 8000000), ("0.12345600", 493824), ("-0.00000025", -1)):
        assert lattice_int(good)[0] == q, good
    for bad in ("0.12345678", "4", "4.00000025", "", "NaN", "inf", "1e-3", " 0.5", "0.5x", "-"):
        _expect_failure(f"lattice {bad!r}", lambda bad=bad: lattice_int(bad))
        _expect_failure(f"decimal {bad!r}", lambda bad=bad: decimal_lattice(bad, "t"))

    # 2. end-to-end build + verify on synthetic country CSVs
    labels = [f"m{4001.6 - 1.93 * i:.1f}" for i in range(N_SPECTRAL)]
    header = ",".join(list(BOOKKEEPING_COLUMNS) + labels)
    saved = (_header_sha256, _no_spectrum_ssns, _three_replicate_ssns)
    _header_sha256 = hashlib.sha256(header.encode("ascii")).hexdigest()
    _no_spectrum_ssns = frozenset({"icr000006"})
    _three_replicate_ssns = frozenset({"icr000007"})

    def spectrum() -> list[str]:
        base = rng.uniform(0.3, 1.0)
        return [_lattice_text(int((base + 1.5 * math.sin(i / 97.0) ** 2) * LATTICE_PER_UNIT) // 1 + rng.randrange(-40, 40))
                for i in range(N_SPECTRAL)]

    def three_replicate_spectrum() -> list[str]:
        base = rng.uniform(0.3, 1.0)
        return [_three_replicate_text(int((base + math.cos(i / 61.0) ** 2) * 3_000_000) + rng.randrange(-30, 30))
                for i in range(N_SPECTRAL)]

    three = three_replicate_spectrum()
    four = spectrum()
    assert is_three_replicate_row(three) and decimal_three_replicate(three)
    assert not is_three_replicate_row(four) and not decimal_three_replicate(four)
    assert not is_three_replicate_row(three[:-1] + ["0.12345678"])
    assert not decimal_three_replicate(three[:-1] + ["0.12345678"])
    assert not is_three_replicate_row(["0.5"] * N_SPECTRAL) and not decimal_three_replicate(["0.5"] * N_SPECTRAL)
    _expect_failure("3-replicate row on the 2.5e-7 path", lambda: convert_row(three, "t", {}))

    with tempfile.TemporaryDirectory(prefix="afsis_selftest_", dir="/tmp") as tmp_name:
        tmp = Path(tmp_name)
        data_root = tmp / "data"
        csv_dir = data_root / "downloads" / DATASET_ID / "csv"
        csv_dir.mkdir(parents=True)
        dup = spectrum()
        files = {
            "1_alpha.csv": ("Alpha", [("1", "icr000001", "Topsoil", spectrum()),
                                      ("2", "icr000002", "Subsoil", dup),
                                      ("3", "icr000006", "Subsoil", ["NA"] * N_SPECTRAL),
                                      ("4", "icr000007", "Topsoil", three)]),
            "2_beta.csv": ("Beta Land", [("1", "icr000003", "Topsoil", spectrum()),
                                         ("2", "icr000004", "Subsoil", list(dup)),
                                         ("3", "icr000005", "Topsoil", spectrum())]),
        }
        source_lines = ["datafile_id\tlocal_filename\tupstream_ingested_name\tcountry_column_value\t"
                        "original_size_bytes\toriginal_md5"]
        for number, (name, (country, rows)) in enumerate(files.items(), 1):
            body = header + "\r\n" + "".join(
                ",".join([num, ssn, depth, country] + cells) + "\r\n" for num, ssn, depth, cells in rows
            )
            path = csv_dir / name
            path.write_bytes(body.encode("ascii"))
            size, md5, _ = file_digests(path)
            source_lines.append(f"{number}\t{name}\t{name}\t{country}\t{size}\t{md5}")
        sources_path = tmp / "sources.tsv"
        sources_path.write_text("\n".join(source_lines) + "\n", encoding="utf-8")
        ns = argparse.Namespace(
            sources=sources_path, csv_dir=csv_dir, data_root=data_root,
            samples_dir=data_root / "samples" / DATASET_ID,
            index=data_root / "index" / DATASET_ID / "samples.jsonl",
            stats=data_root / "filtered" / DATASET_ID / "ingest_stats.json",
            manifest=None,
        )
        stats = build(ns)
        assert stats["sample_count"] == 4 and len(stats["duplicate_spectra_dropped"]) == 1, stats
        assert [r["ssn"] for r in stats["excluded_no_spectrum_rows"]] == ["icr000006"], stats
        assert [r["ssn"] for r in stats["excluded_three_replicate_rows"]] == ["icr000007"], stats
        verify(ns)
        check_file(argparse.Namespace(path=csv_dir / "2_beta.csv", country="Beta Land"))
        _expect_failure("check-file wrong country",
                        lambda: check_file(argparse.Namespace(path=csv_dir / "2_beta.csv", country="Alpha")))
        sample = data_root / "samples" / DATASET_ID / SERIES_ID / "icr000003.bin"
        good = sample.read_bytes()
        sample.write_bytes(good[:-4] + struct.pack("<f", 9.5))
        _expect_failure("tampered sample", lambda: verify(ns))
        sample.write_bytes(good)
        (sample.parent / "stray.bin").write_bytes(good)
        _expect_failure("stray sample file", lambda: verify(ns))
        (sample.parent / "stray.bin").unlink()
        verify(ns)

        def corrupt(transform, label: str) -> None:
            path = csv_dir / "2_beta.csv"
            original = path.read_bytes()
            path.write_bytes(transform(original.decode("ascii")).encode("ascii"))
            size, md5, _ = file_digests(path)
            lines = sources_path.read_text(encoding="utf-8").splitlines()
            fields = lines[2].split("\t")
            fields[4:6] = [str(size), md5]
            patched = lines[:2] + ["\t".join(fields)] + lines[3:]
            original_sources = sources_path.read_text(encoding="utf-8")
            sources_path.write_text("\n".join(patched) + "\n", encoding="utf-8")
            try:
                _expect_failure(label, lambda: build(ns))
            finally:
                path.write_bytes(original)
                sources_path.write_text(original_sources, encoding="utf-8")

        first_cell = re.compile(r"(icr000005,Topsoil,Beta Land,)[^,]+")
        corrupt(lambda t: t.replace("icr000005,Topsoil", "icr000001,Topsoil"), "duplicate SSN")
        corrupt(lambda t: t.replace("icr000005,Topsoil", "icr000005,Deep"), "bad depth")
        corrupt(lambda t: first_cell.sub(r"\g<1>", t), "empty cell")
        corrupt(lambda t: first_cell.sub(r"\g<1>NaN", t), "NaN cell")
        corrupt(lambda t: first_cell.sub(r"\g<1>NA", t), "NA cell")
        corrupt(lambda t: first_cell.sub(r"\g<1>1.5e-3", t), "exponent cell")
        corrupt(lambda t: t.rsplit(",", 1)[0] + ",0.12345678\r\n", "off-lattice cell")
        whole_row = re.compile(r"(icr000005,Topsoil,Beta Land),[^\r]*")
        corrupt(lambda t: whole_row.sub(lambda m: m.group(1) + "," + ",".join(["NA"] * N_SPECTRAL), t),
                "unpinned all-NA row")
        corrupt(lambda t: whole_row.sub(lambda m: m.group(1) + "," + ",".join(three_replicate_spectrum()), t),
                "unpinned 3-replicate row")
        corrupt(lambda t: t.rsplit(",", 1)[0] + ",4.5\r\n", "absorbance >= 4")
        corrupt(lambda t: t.replace("m4001.6", "m4001.7", 1), "different grid header")
        corrupt(lambda t: t.replace("icr000005,Topsoil,Beta Land,", "icr000005,Topsoil,Beta Land,0.5,", 1),
                "extra column")
        # build after the corruption round-trips must still reproduce verified output
        build(ns)
        verify(ns)
    _header_sha256, _no_spectrum_ssns, _three_replicate_ssns = saved
    print("selftest_ok")


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check-listing")
    p.add_argument("--json", type=Path, required=True)
    p.add_argument("--sources", type=Path, required=True)
    p.set_defaults(func=check_listing)

    p = sub.add_parser("check-file")
    p.add_argument("--path", type=Path, required=True)
    p.add_argument("--country", required=True)
    p.set_defaults(func=check_file)

    for name, func in (("build", build), ("verify", verify)):
        p = sub.add_parser(name)
        p.add_argument("--sources", type=Path, required=True)
        p.add_argument("--csv-dir", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--samples-dir", type=Path, required=True)
        p.add_argument("--index", type=Path, required=True)
        p.add_argument("--stats", type=Path, required=True)
        p.add_argument("--manifest", type=Path, default=None)
        p.set_defaults(func=func)

    p = sub.add_parser("selftest")
    p.set_defaults(func=selftest)

    args = parser.parse_args()
    try:
        args.func(args)
    except RecipeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
