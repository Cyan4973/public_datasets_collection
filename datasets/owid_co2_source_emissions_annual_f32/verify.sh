#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="owid_co2_source_emissions_annual_f32"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
FILTERED_ROOT="${DATA_DIR}/filtered/${DATASET_ID}"
INDEX_ROOT="${DATA_DIR}/index/${DATASET_ID}"
SAMPLES_ROOT="${DATA_DIR}/samples/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/verify.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/verify.latest.log"

mkdir -p "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() { cp "${LOG_FILE}" "${LATEST_LOG}"; }
trap sync_latest_log EXIT

say() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }

say "download_root=${DOWNLOAD_ROOT}"
say "filtered_root=${FILTERED_ROOT}"
say "index_root=${INDEX_ROOT}"
say "samples_root=${SAMPLES_ROOT}"
say "log_file=${LOG_FILE}"

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" FILTERED_ROOT="${FILTERED_ROOT}" INDEX_ROOT="${INDEX_ROOT}" SAMPLES_ROOT="${SAMPLES_ROOT}" python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import array
import csv
import json
import math
import os
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "owid_co2_source_emissions_annual_f32"
sample_format = "raw homogeneous float32 annual CO2 source-emissions column"
natural_record_kind = "owid_co2_source_emissions_column"
unit = "million tonnes CO2"
min_sources = int(os.environ.get("OWID_CO2_SOURCE_MIN_SOURCES", "5"))
min_column_values = int(os.environ.get("OWID_CO2_SOURCE_MIN_COLUMN_VALUES", "5000"))
min_total_values = int(os.environ.get("OWID_CO2_SOURCE_MIN_TOTAL_VALUES", "50000"))
source_defs = [
    ("coal_co2", "owid_coal_co2_mt_f32"),
    ("oil_co2", "owid_oil_co2_mt_f32"),
    ("gas_co2", "owid_gas_co2_mt_f32"),
    ("cement_co2", "owid_cement_co2_mt_f32"),
    ("flaring_co2", "owid_flaring_co2_mt_f32"),
]
failures_path = download_root / "download_failures.tsv"
if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")
source_csv = Path(os.environ.get("OWID_CO2_SOURCE_CSV", download_root / "owid-co2-data.csv"))
if not source_csv.is_file():
    raise SystemExit(f"missing raw CSV: {source_csv}")
stats_path = filtered_root / "source_stats.tsv"
index_path = index_root / "samples.jsonl"
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

stats_rows = {}
with stats_path.open("r", encoding="utf-8", newline="") as handle:
    for row in csv.DictReader(handle, delimiter="\t"):
        stats_rows[row["owid_column"]] = row

records_by_column = {column: [] for column, _ in source_defs}
row_counts = {column: 0 for column, _ in source_defs}
blank_counts = {column: 0 for column, _ in source_defs}
parse_counts = {column: 0 for column, _ in source_defs}
iso_sets = {column: set() for column, _ in source_defs}
with source_csv.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    required = {"iso_code", "year", *(column for column, _ in source_defs)}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise SystemExit(f"missing required columns in {source_csv}: {reader.fieldnames!r}")
    for row in reader:
        iso_code = str(row.get("iso_code", "")).strip()
        if not (len(iso_code) == 3 and iso_code.isalpha() and iso_code.upper() == iso_code):
            continue
        raw_year = str(row.get("year", "")).strip()
        try:
            year = int(raw_year)
        except ValueError:
            for column, _ in source_defs:
                parse_counts[column] += 1
            continue
        if year < 1700 or year > 2100:
            for column, _ in source_defs:
                parse_counts[column] += 1
            continue
        for column, _ in source_defs:
            row_counts[column] += 1
            raw_value = str(row.get(column, "")).strip()
            if raw_value == "":
                blank_counts[column] += 1
                continue
            try:
                value = float(raw_value)
            except ValueError:
                parse_counts[column] += 1
                continue
            if not math.isfinite(value):
                parse_counts[column] += 1
                continue
            records_by_column[column].append((iso_code, year, value))
            iso_sets[column].add(iso_code)

expected_records = {}
for column, series_id in source_defs:
    parsed = sorted(records_by_column[column], key=lambda item: (item[0], item[1]))
    values = [value for _, _, value in parsed]
    stats_row = stats_rows.get(column)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {column}")
    checks = {
        "row_count": row_counts[column],
        "kept_count": len(values),
        "skipped_blank_count": blank_counts[column],
        "skipped_parse_count": parse_counts[column],
        "country_count": len(iso_sets[column]),
    }
    for field, expected_value in checks.items():
        if int(stats_row[field]) != expected_value:
            raise SystemExit(f"stats mismatch for {column} {field}: {stats_row[field]} != {expected_value}")
    start_year = min((year for _, year, _ in parsed), default="")
    end_year = max((year for _, year, _ in parsed), default="")
    if str(stats_row["start_year"]) != str(start_year) or str(stats_row["end_year"]) != str(end_year):
        raise SystemExit(f"year-range mismatch for {column}")
    if len(values) < min_column_values:
        continue
    sample_path = samples_root / series_id / f"{column}_iso_country_year.bin"
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    sample_size_bytes = sample_path.stat().st_size
    expected_size = len(values) * 4
    if sample_size_bytes != expected_size:
        raise SystemExit(f"wrong sample size for {sample_path}: {sample_size_bytes} != {expected_size}")
    payload = array.array("f")
    with sample_path.open("rb") as handle:
        payload.frombytes(handle.read())
    if payload.itemsize > 1 and os.sys.byteorder != "little":
        payload.byteswap()
    if len(payload) != len(values):
        raise SystemExit(f"payload length mismatch for {sample_path}")
    if min(payload) == max(payload):
        raise SystemExit(f"constant source-emissions column rejected: {sample_path}")
    expected_records[column] = {
        "dataset_id": dataset_id,
        "series_id": series_id,
        "sample_path": sample_path.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": sample_size_bytes,
        "value_count": len(values),
        "sample_format": sample_format,
        "sample_geometry": "table_column",
        "sample_rank": 1,
        "sample_axes": ["iso_country_year_row"],
        "natural_record_kind": natural_record_kind,
        "owid_column": column,
        "unit": unit,
        "country_count": len(iso_sets[column]),
        "start_year": start_year,
        "end_year": end_year,
        "min": min(values),
        "max": max(values),
    }

total_values = sum(int(record["value_count"]) for record in expected_records.values())
total_bytes = sum(int(record["sample_size_bytes"]) for record in expected_records.values())
if len(expected_records) < min_sources:
    raise SystemExit(f"insufficient accepted source columns: {len(expected_records)} < {min_sources}")
if total_values < min_total_values:
    raise SystemExit(f"insufficient total values: {total_values} < {min_total_values}")

index_records = {}
with index_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("dataset_id") != dataset_id:
            raise SystemExit(f"unexpected dataset id on line {line_number}: {record}")
        key = record.get("owid_column")
        if key in index_records:
            raise SystemExit(f"duplicate index entry for {key} on line {line_number}")
        index_records[key] = record
if set(index_records) != set(expected_records):
    raise SystemExit(f"sample index keys do not match samples: index={sorted(index_records)} expected={sorted(expected_records)}")
for key, expected in expected_records.items():
    record = index_records[key]
    for field, expected_value in expected.items():
        observed = record.get(field)
        if isinstance(expected_value, float):
            if abs(float(observed) - expected_value) > 1e-6:
                raise SystemExit(f"index mismatch for {key} {field}: {observed!r} != {expected_value!r}")
        elif observed != expected_value:
            raise SystemExit(f"index mismatch for {key} {field}: {observed!r} != {expected_value!r}")
print(f"verified_rows={len(expected_records)} primary_values={total_values} primary_bytes={total_bytes}")
PY

say "verified raw inventory, generated sample sizes, stats, and sample index"
