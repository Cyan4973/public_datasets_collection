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
LOG_FILE="${LOG_ROOT}/build.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/build.latest.log"

mkdir -p "${FILTERED_ROOT}" "${INDEX_ROOT}" "${SAMPLES_ROOT}" "${LOG_ROOT}"
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
import shutil
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
source_csv = Path(os.environ.get("OWID_CO2_SOURCE_CSV", download_root / "owid-co2-data.csv"))
if not source_csv.is_file():
    raise SystemExit(f"missing raw CSV: {source_csv}")

for _, series_id in source_defs:
    series_dir = samples_root / series_id
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "source_stats.tsv"
index_path = index_root / "samples.jsonl"
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

index_records = []
accepted = []
with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow([
        "owid_column",
        "series_id",
        "row_count",
        "kept_count",
        "skipped_blank_count",
        "skipped_parse_count",
        "country_count",
        "start_year",
        "end_year",
        "min",
        "max",
    ])
    for column, series_id in source_defs:
        parsed = sorted(records_by_column[column], key=lambda item: (item[0], item[1]))
        values = [value for _, _, value in parsed]
        start_year = min((year for _, year, _ in parsed), default="")
        end_year = max((year for _, year, _ in parsed), default="")
        value_min = min(values) if values else ""
        value_max = max(values) if values else ""
        writer.writerow([
            column,
            series_id,
            row_counts[column],
            len(values),
            blank_counts[column],
            parse_counts[column],
            len(iso_sets[column]),
            start_year,
            end_year,
            value_min,
            value_max,
        ])
        if len(values) < min_column_values:
            continue
        payload = array.array("f", values)
        if payload.itemsize > 1 and os.sys.byteorder != "little":
            payload.byteswap()
        out_path = samples_root / series_id / f"{column}_iso_country_year.bin"
        with out_path.open("wb") as out_file:
            out_file.write(payload.tobytes())
        sample_size_bytes = out_path.stat().st_size
        record = {
            "dataset_id": dataset_id,
            "series_id": series_id,
            "sample_path": out_path.relative_to(data_root).as_posix(),
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
            "min": value_min,
            "max": value_max,
        }
        index_records.append(record)
        accepted.append(record)

total_values = sum(int(record["value_count"]) for record in accepted)
total_bytes = sum(int(record["sample_size_bytes"]) for record in accepted)
if len(accepted) < min_sources:
    raise SystemExit(f"insufficient accepted source columns: {len(accepted)} < {min_sources}")
if total_values < min_total_values:
    raise SystemExit(f"insufficient total values: {total_values} < {min_total_values}")

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
print(f"built_samples={len(accepted)} primary_values={total_values} primary_bytes={total_bytes}")
PY

say "built samples under ${SAMPLES_ROOT}"
