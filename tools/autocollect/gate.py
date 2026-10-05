#!/usr/bin/env python3
"""Deterministic acceptance gate for one recipe directory.

Checks only the mechanical parts of collection_protocol.md: required files,
manifest fields, sample index consistency, primary floors and cap, claimed
versus realized scope, opaque-byte markers, and constant series. Everything
that needs judgment (novelty, homogeneity, proxy-ness, licensing, synthetic
numericization) belongs to the judge; heuristics that hint at those problems
are reported as warnings, never failures.

Usage: gate.py staging/<dataset_id> [--json]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import struct
import subprocess
import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from audit_acceptance import MIN_MEDIAN_SAMPLE_VALUES, MIN_SAMPLE_BYTES, MIN_VALUES, classify  # noqa: E402
from audit_series_quality import FMT_MAP, MINORITY_THRESHOLD  # noqa: E402
from check_repo_hygiene import (  # noqa: E402
    AMBIGUOUS_NATURAL_RECORD_KINDS,
    NON_ACTIVE_DATASET_STATUSES,
    OPAQUE_PRIMARY_REPRESENTATION_CLASSES,
    OPAQUE_PRIMARY_TEXT_PATTERNS,
    OPAQUE_SOURCE_FIELDS,
    joined_series_text,
)

MAX_PRIMARY_BYTES = 1_000_000_000
REQUIRED_FILES = ["manifest.toml", "README.md", "download.sh", "build.sh", "verify.sh"]
REQUIRED_PRIMARY_KEYS = [
    "id",
    "semantic_meaning",
    "missing_value_policy",
    "conversion",
    "numeric_kind",
    "bit_width",
    "endianness",
    "sample_count",
    "total_size_bytes",
    "output_path",
    "representation_class",
    "natural_record_kind",
    "source_format",
    "source_field",
]
REPRESENTATION_CLASSES = {"native_numeric", "derived_operational_numeric"}
INDEX_KEYS = [
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
]
CREDENTIAL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"authorization:",
        r"bearer\s",
        r"\.netrc",
        r"--user\s",
        r"\$\{?\w*(api_?key|token|secret|password)\w*\}?",
        r"x-api-key",
        r"requester-?pays",
    ]
]
SCAN_VALUES_PER_SERIES = 2_000_000
SCAN_FILES_PER_SERIES = 200
FULL_CONSTANT_CHECK_BYTES = 64 * 1024 * 1024


def read_chunks(path: Path, size: int, element: int, budget_values: int) -> bytes:
    """Head and middle slices of a sample, aligned to the element size."""
    budget = max(element, (budget_values * element) // element * element)
    if size <= budget:
        return path.read_bytes()
    half = budget // 2 // element * element
    middle = (size // 2) // element * element
    with path.open("rb") as fh:
        head = fh.read(half)
        fh.seek(middle)
        return head + fh.read(half)


def is_constant(raw: bytes, element: int) -> bool:
    if len(raw) < 2 * element:
        return True
    first = raw[:element]
    return raw == first * (len(raw) // element)


def scan_series(series: dict, rows: list[dict], data_root: Path) -> tuple[dict, list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    kind = str(series.get("numeric_kind"))
    width = int(series.get("bit_width", 0))
    fmt = FMT_MAP.get((kind, width))
    sid = str(series.get("id"))
    stats: dict = {"scanned_files": 0, "scanned_values": 0}
    if fmt is None or not rows:
        return stats, failures, warnings
    element = width // 8
    step = max(1, len(rows) // SCAN_FILES_PER_SERIES)
    chosen = rows[::step][:SCAN_FILES_PER_SERIES]
    per_file = max(1_000, SCAN_VALUES_PER_SERIES // len(chosen))
    counts: collections.Counter = collections.Counter()
    constant_samples = 0
    nan_values = 0
    non_integral = 0
    f32_exact = True
    minimum = math.inf
    maximum = -math.inf
    for row in chosen:
        path = data_root / row["sample_path"]
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size <= FULL_CONSTANT_CHECK_BYTES:
            raw = path.read_bytes()
            if is_constant(raw, element):
                constant_samples += 1
            raw = read_chunks(path, size, element, per_file) if size > per_file * element else raw
        else:
            raw = read_chunks(path, size, element, per_file)
            if is_constant(raw, element):
                constant_samples += 1
        raw = raw[: len(raw) // element * element]
        stats["scanned_files"] += 1
        for (value,) in struct.iter_unpack("<" + fmt, raw):
            stats["scanned_values"] += 1
            if kind == "float" and width >= 32:
                if value != value:
                    nan_values += 1
                    continue
                if math.isfinite(value):
                    if value != int(value):
                        non_integral += 1
                    if width == 64 and f32_exact:
                        try:
                            f32_exact = struct.unpack("<f", struct.pack("<f", value))[0] == value
                        except OverflowError:
                            f32_exact = False
            if len(counts) <= 65_536:
                counts[value] += 1
            if value == value:
                minimum = min(minimum, value)
                maximum = max(maximum, value)
    scanned = stats["scanned_values"]
    stats.update(
        {
            "distinct_values_capped": len(counts),
            "min": None if minimum == math.inf else minimum,
            "max": None if maximum == -math.inf else maximum,
            "constant_samples": constant_samples,
            "nan_fraction": round(nan_values / scanned, 6) if scanned else 0,
        }
    )
    if stats["scanned_files"] and constant_samples == stats["scanned_files"]:
        failures.append(f"series {sid}: every scanned sample is constant")
    elif constant_samples:
        warnings.append(f"series {sid}: {constant_samples}/{stats['scanned_files']} scanned samples are constant")
    if len(counts) == 2 and scanned:
        minority = min(counts.values()) / sum(counts.values())
        if minority < MINORITY_THRESHOLD:
            warnings.append(f"series {sid}: binary-sparse in scanned values (minority fraction {minority:.6f})")
    if stats["nan_fraction"] > 0.5:
        warnings.append(f"series {sid}: {stats['nan_fraction']:.0%} of scanned values are NaN")
    if scanned and kind in {"int", "uint"} and width >= 32 and maximum != -math.inf:
        if minimum >= -(2**15) and maximum < 2**16:
            warnings.append(f"series {sid}: scanned {kind}{width} values fit in 16 bits (range {minimum}..{maximum}); possible hollow width")
    if scanned and kind == "float" and width >= 32 and non_integral == 0 and scanned > nan_values:
        warnings.append(f"series {sid}: every scanned float value is integral; check for widened integer codes")
    if scanned and kind == "float" and width == 64 and f32_exact and scanned > nan_values:
        warnings.append(f"series {sid}: every scanned float64 value round-trips through float32; check for widening")
    return stats, failures, warnings


def load_registry() -> dict[str, str]:
    path = REPO_ROOT / "attempts" / "dataset_status.tsv"
    statuses: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 2:
                statuses[parts[0]] = parts[1]
    return statuses


def gate(recipe_dir: Path, data_root: Path) -> dict:
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict = {}
    dataset_id = recipe_dir.name
    report = {"dataset_id": dataset_id, "recipe_dir": str(recipe_dir), "failures": failures, "warnings": warnings, "metrics": metrics}

    for name in REQUIRED_FILES:
        if not (recipe_dir / name).is_file():
            failures.append(f"missing required file {name}")
    for script in ("download.sh", "build.sh", "verify.sh"):
        path = recipe_dir / script
        if path.is_file():
            check = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            if check.returncode != 0:
                failures.append(f"{script}: bash syntax error: {check.stderr.strip()[:300]}")
    for path in sorted(recipe_dir.rglob("*")):
        if path.is_file() and path.suffix in {".sh", ".py"} and path.stat().st_size < 2_000_000:
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in CREDENTIAL_PATTERNS:
                if pattern.search(text):
                    warnings.append(f"{path.relative_to(recipe_dir)}: credential-like pattern {pattern.pattern!r}; recipes must use public anonymous access")

    registry_status = load_registry().get(dataset_id)
    if registry_status in NON_ACTIVE_DATASET_STATUSES:
        failures.append(f"dataset_id {dataset_id} is registered as {registry_status}; pick a new id or record a deliberate retry")
    if recipe_dir.parent.name == "staging" and (REPO_ROOT / "datasets" / dataset_id).exists():
        failures.append(f"datasets/{dataset_id} already exists")

    manifest_path = recipe_dir / "manifest.toml"
    if not manifest_path.is_file():
        report["ok"] = False
        return report
    try:
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        failures.append(f"manifest.toml does not parse: {exc}")
        report["ok"] = False
        return report

    if manifest.get("dataset_id") != dataset_id:
        failures.append(f"manifest dataset_id {manifest.get('dataset_id')!r} != directory name {dataset_id!r}")
    license_table = manifest.get("license", {})
    if not isinstance(license_table, dict) or not (license_table.get("spdx") or license_table.get("name")) or not license_table.get("url"):
        failures.append("manifest [license] needs spdx or name, plus url")

    series_by_id: dict[str, dict] = {}
    for index, series in enumerate(manifest.get("series", []), 1):
        if not isinstance(series, dict):
            continue
        sid = str(series.get("id", f"series_{index}"))
        series_by_id[sid] = series
        role = series.get("role")
        if role not in {"primary", "auxiliary"}:
            failures.append(f"series {sid}: role must be 'primary' or 'auxiliary', got {role!r}")
            continue
        if role != "primary":
            continue
        missing = [key for key in REQUIRED_PRIMARY_KEYS if key not in series or series[key] in ("", None)]
        if missing:
            failures.append(f"series {sid}: missing primary fields {missing}")
        if series.get("representation_class") not in REPRESENTATION_CLASSES:
            failures.append(f"series {sid}: representation_class must be one of {sorted(REPRESENTATION_CLASSES)}")
        if series.get("representation_class") in OPAQUE_PRIMARY_REPRESENTATION_CLASSES:
            failures.append(f"series {sid}: opaque representation_class")
        if str(series.get("natural_record_kind", "")).strip() in AMBIGUOUS_NATURAL_RECORD_KINDS:
            failures.append(f"series {sid}: natural_record_kind must name a specific source record")
        if str(series.get("source_field", "")).strip().lower() in OPAQUE_SOURCE_FIELDS:
            failures.append(f"series {sid}: source_field must name the decoded typed field")
        text = joined_series_text(series)
        for pattern_name, needles in OPAQUE_PRIMARY_TEXT_PATTERNS:
            if all(needle in text for needle in needles):
                failures.append(f"series {sid}: opaque container/file bytes wording ({pattern_name})")
        if (str(series.get("numeric_kind")), series.get("bit_width")) not in FMT_MAP:
            failures.append(f"series {sid}: unsupported numeric_kind/bit_width {series.get('numeric_kind')}/{series.get('bit_width')}")
        if series.get("bit_width") != 8 and series.get("endianness") != "little":
            warnings.append(f"series {sid}: endianness {series.get('endianness')!r}; repository samples are little-endian")
    primary_ids = [sid for sid, series in series_by_id.items() if series.get("role") == "primary"]
    if not primary_ids:
        failures.append("manifest declares no primary series")

    index_path = data_root / "index" / dataset_id / "samples.jsonl"
    if not index_path.is_file():
        failures.append(f"missing sample index {index_path.relative_to(REPO_ROOT) if index_path.is_relative_to(REPO_ROOT) else index_path}")
        report["ok"] = False
        return report

    rows_by_series: dict[str, list[dict]] = collections.defaultdict(list)
    for line_number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            failures.append(f"index line {line_number}: invalid JSON")
            continue
        missing = [key for key in INDEX_KEYS if key not in row]
        if missing:
            failures.append(f"index line {line_number}: missing keys {missing}")
            continue
        sid = str(row["series_id"])
        series = series_by_id.get(sid)
        if row["dataset_id"] != dataset_id:
            failures.append(f"index line {line_number}: dataset_id {row['dataset_id']!r}")
        if series is None:
            failures.append(f"index line {line_number}: series {sid!r} not declared in manifest")
            continue
        if (row["numeric_kind"], int(row["bit_width"])) != (series.get("numeric_kind"), series.get("bit_width")):
            failures.append(f"index line {line_number}: kind/width {row['numeric_kind']}/{row['bit_width']} disagree with manifest series {sid}")
        element = int(row["element_size_bytes"])
        if element * 8 != int(row["bit_width"]):
            failures.append(f"index line {line_number}: element_size_bytes {element} != bit_width/8")
        expected = int(row["value_count"]) * element
        sample_path = data_root / row["sample_path"]
        if not sample_path.is_file():
            failures.append(f"index line {line_number}: missing sample file {row['sample_path']}")
            continue
        actual = sample_path.stat().st_size
        if actual != int(row["sample_size_bytes"]) or actual != expected:
            failures.append(
                f"index line {line_number}: size mismatch file={actual} index={row['sample_size_bytes']} value_count*element={expected}"
            )
        rows_by_series[sid].append(row)
        if len([f for f in failures if f.startswith("index line")]) > 20:
            failures.append("too many index errors; stopping index scan")
            break

    primary_values = primary_bytes = 0
    value_counts: list[int] = []
    series_metrics: dict = {}
    for sid, series in series_by_id.items():
        rows = rows_by_series.get(sid, [])
        values = sum(int(row["value_count"]) for row in rows)
        size = sum(int(row["sample_size_bytes"]) for row in rows)
        if series.get("sample_count") != len(rows):
            failures.append(f"series {sid}: manifest sample_count {series.get('sample_count')} != indexed samples {len(rows)}")
        if series.get("total_size_bytes") != size:
            failures.append(f"series {sid}: manifest total_size_bytes {series.get('total_size_bytes')} != indexed bytes {size}")
        entry = {"role": series.get("role"), "kind": series.get("numeric_kind"), "bit_width": series.get("bit_width"), "samples": len(rows), "values": values, "bytes": size}
        if series.get("role") == "primary":
            primary_values += values
            primary_bytes += size
            value_counts += [int(row["value_count"]) for row in rows]
            scan, scan_failures, scan_warnings = scan_series(series, rows, data_root)
            entry["scan"] = scan
            failures.extend(scan_failures)
            warnings.extend(scan_warnings)
        series_metrics[sid] = entry

    value_counts.sort()
    median = 0.0
    if value_counts:
        middle = len(value_counts) // 2
        median = float(value_counts[middle]) if len(value_counts) % 2 else (value_counts[middle - 1] + value_counts[middle]) / 2
    status, reasons = classify(primary_values, primary_bytes, len(value_counts), median)
    if status != "ok":
        failures.append(
            f"primary floor: {status} {reasons} (need >= {MIN_VALUES} values or >= {MIN_SAMPLE_BYTES} bytes, median >= {MIN_MEDIAN_SAMPLE_VALUES} values)"
        )
    if primary_bytes > MAX_PRIMARY_BYTES:
        failures.append(f"primary bytes {primary_bytes} exceed cap {MAX_PRIMARY_BYTES}")

    metrics.update(
        {
            "primary_values": primary_values,
            "primary_bytes": primary_bytes,
            "primary_samples": len(value_counts),
            "median_primary_sample_values": median,
            "primary_widths": sorted({int(series_by_id[sid].get("bit_width", 0)) for sid in primary_ids}),
            "series": series_metrics,
        }
    )
    report["ok"] = not failures
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recipe_dir", type=Path)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / ".data")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    recipe_dir = args.recipe_dir.resolve()
    report = gate(recipe_dir, args.data_dir.resolve())
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(f"gate {'PASS' if report['ok'] else 'FAIL'}: {report['dataset_id']}")
        for failure in report["failures"]:
            print(f"FAIL  {failure}")
        for warning in report["warnings"]:
            print(f"WARN  {warning}")
        metrics = report["metrics"]
        if metrics:
            print(
                f"primary: values={metrics['primary_values']} bytes={metrics['primary_bytes']} "
                f"samples={metrics['primary_samples']} median_values={metrics['median_primary_sample_values']} widths={metrics['primary_widths']}"
            )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
