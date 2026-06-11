#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/noaa_ghcn_daily_wesd_by_station"
FILTERED_ROOT="${DATA_DIR}/filtered/noaa_ghcn_daily_wesd_by_station"
INDEX_ROOT="${DATA_DIR}/index/noaa_ghcn_daily_wesd_by_station"
SAMPLES_ROOT="${DATA_DIR}/samples/noaa_ghcn_daily_wesd_by_station"
LOG_ROOT="${DATA_DIR}/logs/noaa_ghcn_daily_wesd_by_station"
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
import csv, gzip, json, os
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

stats_path = filtered_root / "station_year_stats.tsv"
index_path = index_root / "samples.jsonl"
failures_path = download_root / "download_failures.tsv"
station_ids = [
    "USW00000102",
    "USW00000373",
    "USW00003048",
    "USW00003085",
    "USW00003145",
    "USW00003761",
    "USW00003855",
    "USW00003902",
    "USW00003952",
    "USW00004109",
    "USW00004720",
    "USW00004838",
    "USW00004916",
    "USW00012836",
    "USW00012883",
    "USW00012924",
    "USW00012976",
    "USW00013724",
    "USW00013732",
    "USW00013758",
    "USW00013813",
    "USW00013861",
    "USW00013894",
    "USW00013935",
    "USW00013973",
    "USW00013999",
    "USW00014719",
    "USW00014739",
    "USW00014757",
    "USW00014788",
    "USW00014823",
    "USW00014850",
    "USW00014914",
    "USW00014922",
    "USW00014941",
    "USW00021515",
    "USW00023007",
    "USW00023053",
    "USW00023062",
    "USW00023110",
    "USW00023169",
    "USW00023203",
    "USW00023259",
    "USW00024021",
    "USW00024089",
    "USW00024137",
    "USW00024149",
    "USW00024163",
    "USW00024228",
    "USW00024255",
    "USW00025339",
    "USW00025402",
    "USW00026407",
    "USW00026502",
    "USW00026627",
    "USW00053002",
    "USW00053127",
    "USW00053169",
    "USW00053847",
    "USW00053877",
    "USW00053925",
    "USW00053981",
    "USW00054773",
    "USW00054854",
    "USW00063867",
    "USW00064756",
    "USW00093032",
    "USW00093110",
    "USW00093206",
    "USW00093725",
    "USW00093781",
    "USW00093824",
    "USW00093874",
    "USW00093963",
    "USW00094015",
    "USW00094077",
    "USW00094176",
    "USW00094624",
    "USW00094728",
    "USW00094793",
    "USW00094846",
    "USW00094895",
    "USW00094958",
]
YEAR_MIN = 1763
YEAR_MAX = 2026
element_id = "WESD"
series_defs = [
    {"series_id": "ghcn_value_i16", "numeric_kind": "int", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
]
if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

station_names = {}
stations_path = download_root / "ghcnd-stations.txt"
if stations_path.is_file():
    with stations_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            station_id = line[:11].strip()
            if station_id in station_ids:
                station_names[station_id] = line[41:71].strip()

with stats_path.open("r", encoding="utf-8", newline="") as handle:
    stats_rows = list(csv.DictReader(handle, delimiter="\t"))
stats_by_key = {(row["station_id"], row["year"]): row for row in stats_rows}
expected_records = {}

for station_id in station_ids:
    csv_path = download_root / f"{station_id}.csv.gz"
    if not csv_path.is_file():
        raise SystemExit(f"missing raw station file: {csv_path}")
    if csv_path.stat().st_size <= 0:
        raise SystemExit(f"empty raw station file: {csv_path}")
    total_values = 0
    per_year = {}
    with gzip.open(csv_path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 8:
                continue
            row_station, raw_date, row_element, raw_value, _mflag, qflag, _sflag, _obs_time = row[:8]
            if row_station != station_id or row_element != element_id:
                continue
            if len(raw_date) != 8 or not raw_date.isdigit():
                continue
            year = int(raw_date[:4])
            if year < YEAR_MIN or year > YEAR_MAX:
                continue
            bucket = per_year.setdefault(year, {"row_count": 0, "kept_count": 0, "skipped_quality_count": 0, "skipped_parse_count": 0, "start_date": "", "end_date": ""})
            bucket["row_count"] += 1
            if qflag.strip() != "":
                bucket["skipped_quality_count"] += 1
                continue
            try:
                value = int(raw_value)
                obs_month = int(raw_date[4:6])
                obs_day = int(raw_date[6:8])
            except ValueError:
                bucket["skipped_parse_count"] += 1
                continue
            if value < -32768 or value > 32767 or obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31:
                bucket["skipped_parse_count"] += 1
                continue
            total_values += 1
            if bucket["start_date"] == "":
                bucket["start_date"] = raw_date
            bucket["end_date"] = raw_date
            bucket["kept_count"] += 1
    for year in sorted(per_year):
        bucket = per_year[year]
        stats_row = stats_by_key.get((station_id, str(year)))
        if stats_row is None:
            raise SystemExit(f"missing stats row for {station_id} {year}")
        for field in ["row_count", "kept_count", "skipped_quality_count", "skipped_parse_count"]:
            if int(stats_row[field]) != int(bucket[field]):
                raise SystemExit(f"stats mismatch for {station_id} {year} field {field}: stats={stats_row[field]} raw={bucket[field]}")
        if stats_row["start_date"] != bucket["start_date"]:
            raise SystemExit(f"start date mismatch for {station_id} {year}: stats={stats_row['start_date']!r} raw={bucket['start_date']!r}")
        if stats_row["end_date"] != bucket["end_date"]:
            raise SystemExit(f"end date mismatch for {station_id} {year}: stats={stats_row['end_date']!r} raw={bucket['end_date']!r}")
    if total_values == 0:
        continue
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{station_id}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = total_values * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
        expected_records[(series["series_id"], station_id)] = {
            "dataset_id": "noaa_ghcn_daily_wesd_by_station",
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": sample_size_bytes,
            "value_count": total_values,
            "station_id": station_id,
            "element_id": element_id,
            "station_name": station_names.get(station_id, ""),
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
