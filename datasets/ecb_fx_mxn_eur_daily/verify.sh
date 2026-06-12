#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/ecb_fx_mxn_eur_daily"
FILTERED_ROOT="${DATA_DIR}/filtered/ecb_fx_mxn_eur_daily"
INDEX_ROOT="${DATA_DIR}/index/ecb_fx_mxn_eur_daily"
SAMPLES_ROOT="${DATA_DIR}/samples/ecb_fx_mxn_eur_daily"
LOG_ROOT="${DATA_DIR}/logs/ecb_fx_mxn_eur_daily"
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
import csv, json, os
from collections import defaultdict
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "ecb_fx_mxn_eur_daily"
series_key = "MXN.EUR"
series_defs = [
    {"series_id": "ecb_fx_value_f32", "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
]
stats_path = filtered_root / "year_stats.tsv"
index_path = index_root / "samples.jsonl"
failures_path = download_root / "download_failures.tsv"
if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")
with stats_path.open("r", encoding="utf-8", newline="") as handle:
    stats_rows = list(csv.DictReader(handle, delimiter="\t"))
stats_by_year = {row["year"]: row for row in stats_rows}
expected_records = {}
counts = defaultdict(int)

path = download_root / "mxn_eur.csv"
if not path.is_file():
    raise SystemExit(f"missing raw CSV: {path}")
with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    rows_by_year = defaultdict(list)
    for row in reader:
        raw_date = str(row.get("TIME_PERIOD", "")).strip()
        rows_by_year[raw_date[:4] if len(raw_date) >= 4 else "unknown"].append(row)
for year in sorted(y for y in rows_by_year if y.isdigit()):
    row_count = len(rows_by_year[year])
    kept_count = 0
    skipped_blank_count = 0
    skipped_parse_count = 0
    start_date = ""
    end_date = ""
    parsed = []
    for row in rows_by_year[year]:
        raw_date = str(row.get("TIME_PERIOD", "")).strip()
        raw_value = str(row.get("OBS_VALUE", "")).strip()
        if raw_date == "" or raw_value == "":
            skipped_blank_count += 1
            continue
        try:
            float(raw_value)
            year_s, month_s, day_s = raw_date.split("-")
            obs_year = int(year_s)
            obs_month = int(month_s)
            obs_day = int(day_s)
        except (TypeError, ValueError):
            skipped_parse_count += 1
            continue
        if obs_year != int(year) or obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31:
            skipped_parse_count += 1
            continue
        parsed.append(raw_date)
    parsed.sort()
    kept_count = len(parsed)
    counts[year] = kept_count
    if parsed:
        start_date = parsed[0]
        end_date = parsed[-1]
    stats_row = stats_by_year.get(year)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {year}")
    for field, value in [("row_count", row_count), ("kept_count", kept_count), ("skipped_blank_count", skipped_blank_count), ("skipped_parse_count", skipped_parse_count)]:
        if int(stats_row[field]) != value:
            raise SystemExit(f"stats mismatch for {year} field {field}: stats={stats_row[field]} raw={value}")
    if stats_row["start_date"] != start_date or stats_row["end_date"] != end_date:
        raise SystemExit(f"date-range mismatch for {year}")
for year, value_count in sorted(counts.items()):
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{year}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = value_count * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
        expected_records[(series["series_id"], year)] = {
            "dataset_id": dataset_id,
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": sample_size_bytes,
            "value_count": value_count,
            "series_key": series_key,
            "year": int(year),
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
