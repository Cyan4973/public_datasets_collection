#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/owid_trade_co2_annual"
FILTERED_ROOT="${DATA_DIR}/filtered/owid_trade_co2_annual"
INDEX_ROOT="${DATA_DIR}/index/owid_trade_co2_annual"
SAMPLES_ROOT="${DATA_DIR}/samples/owid_trade_co2_annual"
LOG_ROOT="${DATA_DIR}/logs/owid_trade_co2_annual"
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

dataset_id = "owid_trade_co2_annual"
target_column = "trade_co2"
countries = ["USA", "CHN", "IND", "BRA", "DEU", "JPN", "NGA", "MEX", "FRA", "ZAF"]
series_defs = [
    {"series_id": "owid_value_f32", "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
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

stats_rows = {}
with stats_path.open("r", encoding="utf-8", newline="") as handle:
    for row in csv.DictReader(handle, delimiter="\t"):
        stats_rows[row["country_code"]] = row

path = download_root / "owid-co2-data.csv"
if not path.is_file():
    raise SystemExit(f"missing raw CSV: {path}")
rows_by_country = defaultdict(list)
country_names = {}
with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
        iso = str(row.get("iso_code", "")).strip()
        if iso not in countries:
            continue
        rows_by_country[iso].append(row)
        country_names.setdefault(iso, str(row.get("country", iso)).strip() or iso)

expected_records = {}
for country_code in countries:
    row_count = len(rows_by_country[country_code])
    kept = 0
    skipped_blank = 0
    skipped_parse = 0
    start_year = ""
    end_year = ""
    for row in rows_by_country[country_code]:
        raw_year = str(row.get("year", "")).strip()
        raw_value = str(row.get(target_column, "")).strip()
        if raw_year == "" or raw_value == "":
            skipped_blank += 1
            continue
        try:
            year = int(raw_year)
            float(raw_value)
        except ValueError:
            skipped_parse += 1
            continue
        if year < 1800 or year > 2100:
            skipped_parse += 1
            continue
        kept += 1
        if start_year == "":
            start_year = str(year)
        end_year = str(year)
    stats_row = stats_rows.get(country_code)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {country_code}")
    if int(stats_row["row_count"]) != row_count:
        raise SystemExit(f"row_count mismatch for {country_code}")
    if int(stats_row["kept_count"]) != kept:
        raise SystemExit(f"kept_count mismatch for {country_code}")
    if int(stats_row["skipped_blank_count"]) != skipped_blank:
        raise SystemExit(f"skipped_blank_count mismatch for {country_code}")
    if int(stats_row["skipped_parse_count"]) != skipped_parse:
        raise SystemExit(f"skipped_parse_count mismatch for {country_code}")
    if stats_row["start_year"] != start_year or stats_row["end_year"] != end_year:
        raise SystemExit(f"year-range mismatch for {country_code}")
    country_name = country_names.get(country_code, country_code)
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{country_code}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = kept * int(series["element_size_bytes"])
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
            "value_count": kept,
            "country_code": country_code,
            "country_name": country_name,
            "owid_column": target_column,
        }
if not expected_records:
    raise SystemExit("no country samples were produced")

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
