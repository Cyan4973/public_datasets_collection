#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/noaa_ghcn_daily_tsun_by_station"
FILTERED_ROOT="${DATA_DIR}/filtered/noaa_ghcn_daily_tsun_by_station"
INDEX_ROOT="${DATA_DIR}/index/noaa_ghcn_daily_tsun_by_station"
SAMPLES_ROOT="${DATA_DIR}/samples/noaa_ghcn_daily_tsun_by_station"
LOG_ROOT="${DATA_DIR}/logs/noaa_ghcn_daily_tsun_by_station"
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
import array, csv, gzip, json, os, shutil
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "noaa_ghcn_daily_tsun_by_station"
element_id = "TSUN"
station_ids = ["USW00094728", "USW00014922", "USW00094846", "USW00014739", "USW00023062", "USW00025339"]
series_defs = [
    {"series_id": "ghcn_value_i16", "array_type": "h", "numeric_kind": "int", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_year_u16", "array_type": "H", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_month_u8", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
    {"series_id": "obs_day_u8", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
]

station_names = {}
stations_path = download_root / "ghcnd-stations.txt"
if stations_path.is_file():
    with stations_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            station_id = line[:11].strip()
            if station_id in station_ids:
                station_names[station_id] = line[41:71].strip()

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "station_year_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["station_id", "year", "row_count", "kept_count", "skipped_quality_count", "skipped_parse_count", "start_date", "end_date"])
    for station_id in station_ids:
        value_series = []
        year_series = []
        month_series = []
        day_series = []
        csv_path = download_root / f"{station_id}.csv.gz"
        if not csv_path.is_file():
            raise SystemExit(f"missing raw station file: {csv_path}")
        per_year = {year: {"row_count": 0, "kept_count": 0, "skipped_quality_count": 0, "skipped_parse_count": 0, "start_date": "", "end_date": ""} for year in range(2010, 2024)}
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
                if year < 2010 or year > 2023:
                    continue
                bucket = per_year[year]
                bucket["row_count"] += 1
                if qflag.strip() != "":
                    bucket["skipped_quality_count"] += 1
                    continue
                try:
                    value = int(raw_value)
                    obs_year = year
                    obs_month = int(raw_date[4:6])
                    obs_day = int(raw_date[6:8])
                except ValueError:
                    bucket["skipped_parse_count"] += 1
                    continue
                if value < -32768 or value > 32767 or obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31:
                    bucket["skipped_parse_count"] += 1
                    continue
                value_series.append(value)
                year_series.append(obs_year)
                month_series.append(obs_month)
                day_series.append(obs_day)
                bucket["kept_count"] += 1
                if bucket["start_date"] == "":
                    bucket["start_date"] = raw_date
                bucket["end_date"] = raw_date
        for year in range(2010, 2024):
            bucket = per_year[year]
            writer.writerow([station_id, year, bucket["row_count"], bucket["kept_count"], bucket["skipped_quality_count"], bucket["skipped_parse_count"], bucket["start_date"], bucket["end_date"]])
        payloads = {"ghcn_value_i16": value_series, "obs_year_u16": year_series, "obs_month_u8": month_series, "obs_day_u8": day_series}
        for series in series_defs:
            payload = array.array(series["array_type"], payloads[series["series_id"]])
            if payload.itemsize > 1 and os.sys.byteorder != "little":
                payload.byteswap()
            out_path = samples_root / series["series_id"] / f"{station_id}.bin"
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
                "station_id": station_id,
                "element_id": element_id,
                "station_name": station_names.get(station_id, ""),
            })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
PY

say "built samples under ${SAMPLES_ROOT}"
