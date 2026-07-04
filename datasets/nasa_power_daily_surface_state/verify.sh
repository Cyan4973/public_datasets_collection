#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
START_YEAR=${NASA_POWER_DAILY_SURFACE_STATE_START_YEAR:-1981}
END_YEAR=${NASA_POWER_DAILY_SURFACE_STATE_END_YEAR:-2024}
MIN_VALUES_PER_SAMPLE=${NASA_POWER_DAILY_SURFACE_STATE_MIN_VALUES_PER_SAMPLE:-15000}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/nasa_power_daily_surface_state"
FILTERED_ROOT="${DATA_DIR}/filtered/nasa_power_daily_surface_state"
INDEX_ROOT="${DATA_DIR}/index/nasa_power_daily_surface_state"
SAMPLES_ROOT="${DATA_DIR}/samples/nasa_power_daily_surface_state"
LOG_ROOT="${DATA_DIR}/logs/nasa_power_daily_surface_state"
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
say "year_window=${START_YEAR}..${END_YEAR}"
say "min_values_per_sample=${MIN_VALUES_PER_SAMPLE}"

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" FILTERED_ROOT="${FILTERED_ROOT}" INDEX_ROOT="${INDEX_ROOT}" SAMPLES_ROOT="${SAMPLES_ROOT}" START_YEAR="${START_YEAR}" END_YEAR="${END_YEAR}" MIN_VALUES_PER_SAMPLE="${MIN_VALUES_PER_SAMPLE}" python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
start_year = int(os.environ["START_YEAR"])
end_year = int(os.environ["END_YEAR"])
min_values_per_sample = int(os.environ["MIN_VALUES_PER_SAMPLE"])

stats_path = filtered_root / "location_parameter_year_stats.tsv"
index_path = index_root / "samples.jsonl"
failures_path = download_root / "download_failures.tsv"
locations = [
    "san_francisco",
    "phoenix",
    "chicago",
    "miami",
    "anchorage",
    "fairbanks",
    "honolulu",
    "denver",
    "new_orleans",
    "san_juan",
    "seattle",
    "boston",
    "atlanta",
    "dallas",
    "minneapolis",
    "las_vegas",
    "albuquerque",
    "portland",
    "billings",
    "fargo",
]
parameter_series = {
    "PS": {"series_id": "nasa_power_surface_pressure_ps_f64", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    "QV2M": {"series_id": "nasa_power_surface_specific_humidity_qv2m_f64", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    "T2MWET": {"series_id": "nasa_power_surface_wetbulb_t2mwet_f64", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
}
parameter_ids = list(parameter_series)

if failures_path.is_file() and failures_path.stat().st_size > 0:
    active_failures = []
    with failures_path.open("r", encoding="utf-8", newline="") as failures_file:
        for line in failures_file:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                active_failures.append(line.rstrip("\n"))
                continue
            try:
                failure_year = int(parts[1])
            except ValueError:
                active_failures.append(line.rstrip("\n"))
                continue
            if start_year <= failure_year <= end_year:
                active_failures.append(line.rstrip("\n"))
    if active_failures:
        raise SystemExit(f"download failures recorded inside active year window in {failures_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

with stats_path.open("r", encoding="utf-8", newline="") as handle:
    stats_rows = list(csv.DictReader(handle, delimiter="\t"))
stats_by_key = {(row["location_id"], row["parameter_id"], row["year"]): row for row in stats_rows}
expected_records = {}
group_counts = defaultdict(int)

for location_id in locations:
    for year in range(start_year, end_year + 1):
        path = download_root / f"{location_id}_{year}.json"
        if not path.is_file():
            raise SystemExit(f"missing raw JSON: {path}")
        if path.stat().st_size <= 0:
            raise SystemExit(f"empty raw JSON: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        header = payload.get("header", {})
        fill_value = header.get("fill_value")
        parameter_block = payload.get("properties", {}).get("parameter", {})
        if not isinstance(parameter_block, dict):
            raise SystemExit(f"unexpected parameter payload in {path}")
        for parameter_id in parameter_ids:
            values = parameter_block.get(parameter_id)
            if not isinstance(values, dict):
                raise SystemExit(f"missing parameter {parameter_id} in {path}")
            row_count = len(values)
            kept_count = 0
            skipped_fill_count = 0
            skipped_parse_count = 0
            start_date = ""
            end_date = ""
            for date_key in sorted(values):
                raw_value = values[date_key]
                if len(date_key) != 8 or not date_key.isdigit():
                    skipped_parse_count += 1
                    continue
                if raw_value == fill_value:
                    skipped_fill_count += 1
                    continue
                if isinstance(raw_value, str) and raw_value.strip().upper() in {"", "NAN"}:
                    skipped_parse_count += 1
                    continue
                try:
                    float(raw_value)
                    obs_month = int(date_key[4:6])
                    obs_day = int(date_key[6:8])
                except (TypeError, ValueError):
                    skipped_parse_count += 1
                    continue
                if obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31:
                    skipped_parse_count += 1
                    continue
                kept_count += 1
                group_counts[(location_id, parameter_id)] += 1
                if start_date == "":
                    start_date = date_key
                end_date = date_key
            stats_row = stats_by_key.get((location_id, parameter_id, str(year)))
            if stats_row is None:
                raise SystemExit(f"missing stats row for {location_id} {parameter_id} {year}")
            for field, value in [("row_count", row_count), ("kept_count", kept_count), ("skipped_fill_count", skipped_fill_count), ("skipped_parse_count", skipped_parse_count)]:
                if int(stats_row[field]) != value:
                    raise SystemExit(f"stats mismatch for {location_id} {parameter_id} {year} field {field}: stats={stats_row[field]} raw={value}")
            if stats_row["start_date"] != start_date:
                raise SystemExit(f"start date mismatch for {location_id} {parameter_id} {year}: stats={stats_row['start_date']!r} raw={start_date!r}")
            if stats_row["end_date"] != end_date:
                raise SystemExit(f"end date mismatch for {location_id} {parameter_id} {year}: stats={stats_row['end_date']!r} raw={end_date!r}")

for (location_id, parameter_id), value_count in sorted(group_counts.items()):
    if value_count < min_values_per_sample:
        raise SystemExit(f"{location_id} {parameter_id}: only {value_count} values, need {min_values_per_sample}")
    series = parameter_series[parameter_id]
    sample_path = samples_root / series["series_id"] / f"{location_id}.bin"
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    sample_size_bytes = sample_path.stat().st_size
    expected_size = value_count * int(series["element_size_bytes"])
    if sample_size_bytes != expected_size:
        raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
    expected_records[(series["series_id"], location_id)] = {
        "dataset_id": "nasa_power_daily_surface_state",
        "series_id": series["series_id"],
        "sample_path": sample_path.relative_to(data_root).as_posix(),
        "numeric_kind": series["numeric_kind"],
        "bit_width": series["bit_width"],
        "endianness": series["endianness"],
        "element_size_bytes": series["element_size_bytes"],
        "sample_size_bytes": sample_size_bytes,
        "value_count": value_count,
        "location_id": location_id,
        "parameter_id": parameter_id,
        "sample_geometry": "daily_point_time_series",
        "sample_rank": 1,
        "sample_axes": ["day"],
    }

expected_key_count = len(locations) * len(parameter_ids)
if len(expected_records) != expected_key_count:
    raise SystemExit(f"expected {expected_key_count} location-parameter samples, got {len(expected_records)}")

index_records = {}
with index_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        location_id = record.get("location_id", "")
        key = (record.get("series_id"), location_id)
        if key in index_records:
            raise SystemExit(f"duplicate index entry for {key} on line {line_number}")
        index_records[key] = record
if set(index_records) != set(expected_records):
    raise SystemExit(f"sample index keys do not match samples: index={len(index_records)} expected={len(expected_records)}")
for key, expected in expected_records.items():
    record = index_records[key]
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            raise SystemExit(f"index mismatch for {key} field {field}: {record.get(field)!r} != {expected_value!r}")
print("verified raw inventory, generated sample sizes, stats, and sample index")
PY

say "verified raw inventory, generated sample sizes, stats, and sample index"
