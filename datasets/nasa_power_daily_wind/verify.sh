#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/nasa_power_daily_wind"
FILTERED_ROOT="${DATA_DIR}/filtered/nasa_power_daily_wind"
INDEX_ROOT="${DATA_DIR}/index/nasa_power_daily_wind"
SAMPLES_ROOT="${DATA_DIR}/samples/nasa_power_daily_wind"
LOG_ROOT="${DATA_DIR}/logs/nasa_power_daily_wind"
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
import csv, json
from collections import defaultdict
from pathlib import Path
import os

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

stats_path = filtered_root / "location_parameter_year_stats.tsv"
index_path = index_root / "samples.jsonl"
failures_path = download_root / "download_failures.tsv"
locations = ["san_francisco", "phoenix", "chicago", "miami", "anchorage"]
parameter_ids = ["WS2M", "WS10M", "WS50M"]
series_defs = [
    {"series_id": "power_value_f64", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "obs_year_u16", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_month_u8", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
    {"series_id": "obs_day_u8", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
]
if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")
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
    for year in range(2021, 2024):
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
    sample_slug = f"{location_id}_{parameter_id}"
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{sample_slug}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = value_count * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
        expected_records[(series["series_id"], sample_slug)] = {
            "dataset_id": "nasa_power_daily_wind",
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
        }

index_records = {}
with index_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        sample_path = record.get("sample_path")
        sample_key = Path(sample_path).stem if isinstance(sample_path, str) else ""
        key = (record.get("series_id"), sample_key)
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
