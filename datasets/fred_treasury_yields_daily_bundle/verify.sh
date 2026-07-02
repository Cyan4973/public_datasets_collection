#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="fred_treasury_yields_daily_bundle"
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

dataset_id = "fred_treasury_yields_daily_bundle"
series_id = "treasury_yield_percent_f32"
sample_format = "raw homogeneous float32 Treasury yield percent array"
natural_record_kind = "fred_treasury_constant_maturity_series"
min_series = int(os.environ.get("FRED_TREASURY_MIN_SERIES", "8"))
min_sample_values = int(os.environ.get("FRED_TREASURY_MIN_SAMPLE_VALUES", "1000"))
min_total_values = int(os.environ.get("FRED_TREASURY_MIN_TOTAL_VALUES", "100000"))
planned = [
    ("DGS1MO", "1mo", "treasury_1mo.csv"),
    ("DGS3MO", "3mo", "treasury_3mo.csv"),
    ("DGS6MO", "6mo", "treasury_6mo.csv"),
    ("DGS1", "1y", "treasury_1y.csv"),
    ("DGS2", "2y", "treasury_2y.csv"),
    ("DGS3", "3y", "treasury_3y.csv"),
    ("DGS5", "5y", "treasury_5y.csv"),
    ("DGS7", "7y", "treasury_7y.csv"),
    ("DGS10", "10y", "treasury_10y.csv"),
    ("DGS20", "20y", "treasury_20y.csv"),
    ("DGS30", "30y", "treasury_30y.csv"),
]

failures_path = download_root / "download_failures.tsv"
if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")
stats_path = filtered_root / "series_stats.tsv"
index_path = index_root / "samples.jsonl"
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

with stats_path.open("r", encoding="utf-8", newline="") as handle:
    stats_by_series = {row["fred_series_id"]: row for row in csv.DictReader(handle, delimiter="\t")}

expected_records = {}
for fred_series_id, maturity, rel_name in planned:
    path = download_root / rel_name
    if not path.is_file():
        continue
    row_count = 0
    skipped_blank_count = 0
    skipped_parse_count = 0
    parsed = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["observation_date", fred_series_id]:
            raise SystemExit(f"unexpected CSV header in {path}: {reader.fieldnames!r}")
        for row in reader:
            row_count += 1
            raw_date = str(row.get("observation_date", "")).strip()
            raw_value = str(row.get(fred_series_id, "")).strip()
            if raw_date == "" or raw_value in {"", "."}:
                skipped_blank_count += 1
                continue
            try:
                year_s, month_s, day_s = raw_date.split("-")
                year = int(year_s)
                month = int(month_s)
                day = int(day_s)
                value = float(raw_value)
            except (TypeError, ValueError):
                skipped_parse_count += 1
                continue
            if year < 1900 or year > 2100 or month < 1 or month > 12 or day < 1 or day > 31 or not math.isfinite(value):
                skipped_parse_count += 1
                continue
            parsed.append((raw_date, value))
    parsed.sort()
    values = [value for _, value in parsed]
    stats_row = stats_by_series.get(fred_series_id)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {fred_series_id}")
    checks = {
        "row_count": row_count,
        "kept_count": len(values),
        "skipped_blank_count": skipped_blank_count,
        "skipped_parse_count": skipped_parse_count,
    }
    for field, expected_value in checks.items():
        if int(stats_row[field]) != expected_value:
            raise SystemExit(f"stats mismatch for {fred_series_id} {field}: {stats_row[field]} != {expected_value}")
    if len(values) < min_sample_values:
        continue
    sample_path = samples_root / series_id / f"{fred_series_id.lower()}.bin"
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
        raise SystemExit(f"constant yield series rejected: {sample_path}")
    if abs(float(stats_row["min"]) - min(values)) > 1e-9 or abs(float(stats_row["max"]) - max(values)) > 1e-9:
        raise SystemExit(f"stats min/max mismatch for {fred_series_id}")
    expected_records[fred_series_id] = {
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
        "sample_geometry": "time_series",
        "sample_rank": 1,
        "sample_axes": ["observation_day"],
        "natural_record_kind": natural_record_kind,
        "fred_series_id": fred_series_id,
        "maturity": maturity,
        "source_file": rel_name,
        "start_date": parsed[0][0],
        "end_date": parsed[-1][0],
        "min": min(values),
        "max": max(values),
    }

total_values = sum(int(record["value_count"]) for record in expected_records.values())
total_bytes = sum(int(record["sample_size_bytes"]) for record in expected_records.values())
if len(expected_records) < min_series:
    raise SystemExit(f"insufficient accepted maturity series: {len(expected_records)} < {min_series}")
if total_values < min_total_values:
    raise SystemExit(f"insufficient total values: {total_values} < {min_total_values}")

index_records = {}
with index_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("dataset_id") != dataset_id or record.get("series_id") != series_id:
            raise SystemExit(f"unexpected index row on line {line_number}: {record}")
        key = record.get("fred_series_id")
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
