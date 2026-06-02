#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/jhu_covid19_deaths_global_daily"
FILTERED_ROOT="${DATA_DIR}/filtered/jhu_covid19_deaths_global_daily"
INDEX_ROOT="${DATA_DIR}/index/jhu_covid19_deaths_global_daily"
SAMPLES_ROOT="${DATA_DIR}/samples/jhu_covid19_deaths_global_daily"
LOG_ROOT="${DATA_DIR}/logs/jhu_covid19_deaths_global_daily"
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
from datetime import datetime
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "jhu_covid19_deaths_global_daily"
entities = [
    ("us", "US"),
    ("india", "India"),
    ("brazil", "Brazil"),
    ("france", "France"),
    ("germany", "Germany"),
]
series_defs = [
    {"series_id": "death_counts_u32", "numeric_kind": "uint", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
    {"series_id": "obs_year_u16", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_month_u8", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
    {"series_id": "obs_day_u8", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
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
        stats_rows[row["entity_id"]] = row

path = download_root / "time_series_covid19_deaths_global.csv"
if not path.is_file():
    raise SystemExit(f"missing raw CSV: {path}")
with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        raise SystemExit(f"missing CSV header in {path}")
    date_columns = reader.fieldnames[4:]
    parsed_dates = []
    for raw_date in date_columns:
        try:
            dt = datetime.strptime(raw_date, "%m/%d/%y")
        except ValueError:
            parsed_dates.append(None)
        else:
            parsed_dates.append(dt)
    rows = list(reader)
country_rows = defaultdict(list)
for row in rows:
    country_rows[str(row.get("Country/Region", "")).strip()].append(row)

expected_records = {}
for entity_id, country_name in entities:
    matched_rows = country_rows.get(country_name, [])
    kept = 0
    skipped_blank = 0
    skipped_parse = 0
    start_date = ""
    end_date = ""
    for idx, raw_date in enumerate(date_columns):
        dt = parsed_dates[idx]
        if dt is None:
            skipped_parse += 1
            continue
        total = 0
        valid = True
        saw_value = False
        for row in matched_rows:
            raw_value = str(row.get(raw_date, "")).strip()
            if raw_value == "":
                continue
            saw_value = True
            try:
                total += int(raw_value)
            except ValueError:
                valid = False
                break
        if not saw_value:
            skipped_blank += 1
            continue
        if not valid or total < 0:
            skipped_parse += 1
            continue
        kept += 1
        iso_date = dt.strftime("%Y-%m-%d")
        if start_date == "":
            start_date = iso_date
        end_date = iso_date
    stats_row = stats_rows.get(entity_id)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {entity_id}")
    if int(stats_row["row_count"]) != len(date_columns):
        raise SystemExit(f"row_count mismatch for {entity_id}")
    if int(stats_row["kept_count"]) != kept:
        raise SystemExit(f"kept_count mismatch for {entity_id}")
    if int(stats_row["skipped_blank_count"]) != skipped_blank:
        raise SystemExit(f"skipped_blank_count mismatch for {entity_id}")
    if int(stats_row["skipped_parse_count"]) != skipped_parse:
        raise SystemExit(f"skipped_parse_count mismatch for {entity_id}")
    if stats_row["start_date"] != start_date or stats_row["end_date"] != end_date:
        raise SystemExit(f"date-range mismatch for {entity_id}")
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{entity_id}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = kept * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
        expected_records[(series["series_id"], entity_id)] = {
            "dataset_id": dataset_id,
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": sample_size_bytes,
            "value_count": kept,
            "entity_id": entity_id,
            "entity_name": country_name,
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
