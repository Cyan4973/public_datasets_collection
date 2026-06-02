#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="gdelt_events_nummentions_daily"
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

DATASET_ID="${DATASET_ID}" DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" FILTERED_ROOT="${FILTERED_ROOT}" INDEX_ROOT="${INDEX_ROOT}" SAMPLES_ROOT="${SAMPLES_ROOT}" python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import csv, json, os, zipfile
from datetime import datetime
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
dataset_id = os.environ["DATASET_ID"]

days = ["20240101", "20240102", "20240103", "20240104", "20240105", "20240106", "20240107"]
value_index = 31
series_defs = [
    {"series_id": "nummentions_u32", "numeric_kind": "uint", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
    {"series_id": "obs_year_u16", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_month_u8", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
    {"series_id": "obs_day_u8", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
]

stats_path = filtered_root / "day_stats.tsv"
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
stats_by_day = {row["day"]: row for row in stats_rows}
expected_records = {}

for day in days:
    raw_path = download_root / f"{day}.zip"
    if not raw_path.is_file():
        raise SystemExit(f"missing raw zip: {raw_path}")
    row_count = 0
    kept_count = 0
    skipped_blank = 0
    skipped_parse = 0
    with zipfile.ZipFile(raw_path) as zf:
        member_name = zf.namelist()[0]
        with zf.open(member_name, "r") as member:
            for raw_line in member:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                parts = line.split("\t")
                row_count += 1
                if len(parts) <= value_index:
                    skipped_parse += 1
                    continue
                raw_date = parts[1].strip()
                raw_value = parts[value_index].strip()
                if raw_date == "" or raw_value == "":
                    skipped_blank += 1
                    continue
                try:
                    datetime.strptime(raw_date, "%Y%m%d")
                    value = int(raw_value)
                except ValueError:
                    skipped_parse += 1
                    continue
                if value < 0:
                    skipped_parse += 1
                    continue
                kept_count += 1
    stats_row = stats_by_day.get(day)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {day}")
    for field, expected in [("row_count", row_count), ("kept_count", kept_count), ("skipped_blank_count", skipped_blank), ("skipped_parse_count", skipped_parse)]:
        if int(stats_row[field]) != expected:
            raise SystemExit(f"stats mismatch for {day} field {field}: stats={stats_row[field]} raw={expected}")
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{day}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        size = sample_path.stat().st_size
        expected_size = kept_count * int(series["element_size_bytes"])
        if size != expected_size:
            raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {size}")
        expected_records[(series["series_id"], day)] = {
            "dataset_id": dataset_id,
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": size,
            "value_count": kept_count,
            "day": day,
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
