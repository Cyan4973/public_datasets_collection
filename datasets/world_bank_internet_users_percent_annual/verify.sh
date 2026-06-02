#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/world_bank_internet_users_percent_annual"
FILTERED_ROOT="${DATA_DIR}/filtered/world_bank_internet_users_percent_annual"
INDEX_ROOT="${DATA_DIR}/index/world_bank_internet_users_percent_annual"
SAMPLES_ROOT="${DATA_DIR}/samples/world_bank_internet_users_percent_annual"
LOG_ROOT="${DATA_DIR}/logs/world_bank_internet_users_percent_annual"
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
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "world_bank_internet_users_percent_annual"
indicator_id = "IT.NET.USER.ZS"
countries = ["USA", "CHN", "IND", "BRA", "DEU", "JPN", "NGA", "MEX", "FRA", "ZAF"]
series_defs = [
    {"series_id": "internet_users_percent_f64", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "obs_year_u16", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
]
stats_path = filtered_root / "country_stats.tsv"
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
stats_by_country = {row["country_code"]: row for row in stats_rows}
expected_records = {}

for country_code in countries:
    path = download_root / f"{country_code}.json"
    if not path.is_file():
        raise SystemExit(f"missing raw JSON: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload[1]
    row_count = len(rows)
    kept_count = 0
    skipped_null_count = 0
    skipped_parse_count = 0
    start_year = ""
    end_year = ""
    parsed = []
    for row in rows:
        raw_value = row.get("value")
        raw_year = row.get("date")
        if raw_value in ("", None):
            skipped_null_count += 1
            continue
        try:
            value = float(raw_value)
            year = int(str(raw_year))
        except (TypeError, ValueError):
            skipped_parse_count += 1
            continue
        if year < 1900 or year > 2100:
            skipped_parse_count += 1
            continue
        parsed.append((year, value))
    parsed.sort()
    kept_count = len(parsed)
    if parsed:
        start_year = str(parsed[0][0])
        end_year = str(parsed[-1][0])
    stats_row = stats_by_country.get(country_code)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {country_code}")
    for field, value in [("row_count", row_count), ("kept_count", kept_count), ("skipped_null_count", skipped_null_count), ("skipped_parse_count", skipped_parse_count)]:
        if int(stats_row[field]) != value:
            raise SystemExit(f"stats mismatch for {country_code} field {field}: stats={stats_row[field]} raw={value}")
    if stats_row["start_year"] != start_year or stats_row["end_year"] != end_year:
        raise SystemExit(f"year-range mismatch for {country_code}")
    value_count = kept_count
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{country_code}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = value_count * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
        expected_records[(series["series_id"], country_code)] = {
            "dataset_id": dataset_id,
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": sample_size_bytes,
            "value_count": value_count,
            "country_code": country_code,
            "indicator_id": indicator_id,
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
