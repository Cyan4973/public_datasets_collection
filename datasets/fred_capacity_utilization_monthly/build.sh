#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/fred_capacity_utilization_monthly"
FILTERED_ROOT="${DATA_DIR}/filtered/fred_capacity_utilization_monthly"
INDEX_ROOT="${DATA_DIR}/index/fred_capacity_utilization_monthly"
SAMPLES_ROOT="${DATA_DIR}/samples/fred_capacity_utilization_monthly"
LOG_ROOT="${DATA_DIR}/logs/fred_capacity_utilization_monthly"
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
import array, csv, json, os, shutil
from collections import defaultdict
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "fred_capacity_utilization_monthly"
fred_series_id = "TCU"
value_column = "TCU"
series_defs = [
    {"series_id": "fred_value_f32", "array_type": "f", "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
]
for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "year_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []
year_values = defaultdict(list)

path = download_root / "fred_capacity_utilization_monthly.csv"
if not path.is_file():
    raise SystemExit(f"missing raw CSV: {path}")

with path.open("r", encoding="utf-8", newline="") as handle, stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    reader = csv.DictReader(handle)
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["year", "row_count", "kept_count", "skipped_blank_count", "skipped_parse_count", "start_date", "end_date"])
    rows_by_year = defaultdict(list)
    for row in reader:
        raw_date = str(row.get("observation_date", "")).strip()
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
            raw_date = str(row.get("observation_date", "")).strip()
            raw_value = str(row.get(value_column, "")).strip()
            if raw_date == "" or raw_value in {"", "."}:
                skipped_blank_count += 1
                continue
            try:
                value = float(raw_value)
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
            parsed.append((raw_date, value, obs_month, obs_day))
        parsed.sort()
        for raw_date, value, obs_month, obs_day in parsed:
            year_values[year].append(value)
            kept_count += 1
            if start_date == "":
                start_date = raw_date
            end_date = raw_date
        writer.writerow([year, row_count, kept_count, skipped_blank_count, skipped_parse_count, start_date, end_date])

for year in sorted(year_values):
    payloads = {
        "fred_value_f32": year_values[year],
    }
    for series in series_defs:
        payload = array.array(series["array_type"], payloads[series["series_id"]])
        if payload.itemsize > 1 and os.sys.byteorder != "little":
            payload.byteswap()
        out_path = samples_root / series["series_id"] / f"{year}.bin"
        with out_path.open("wb") as out_file:
            out_file.write(payload.tobytes())
        sample_size_bytes = out_path.stat().st_size
        index_records.append({
            "dataset_id": dataset_id,
            "series_id": series["series_id"],
            "sample_path": out_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": sample_size_bytes,
            "value_count": len(payloads[series["series_id"]]),
            "fred_series_id": fred_series_id,
            "year": int(year),
        })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
if not index_records:
    raise SystemExit("no yearly samples were produced")
PY

say "built samples under ${SAMPLES_ROOT}"
