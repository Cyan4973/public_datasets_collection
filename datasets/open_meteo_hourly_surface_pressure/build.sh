#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/open_meteo_hourly_surface_pressure"
FILTERED_ROOT="${DATA_DIR}/filtered/open_meteo_hourly_surface_pressure"
INDEX_ROOT="${DATA_DIR}/index/open_meteo_hourly_surface_pressure"
SAMPLES_ROOT="${DATA_DIR}/samples/open_meteo_hourly_surface_pressure"
LOG_ROOT="${DATA_DIR}/logs/open_meteo_hourly_surface_pressure"
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

dataset_id = "open_meteo_hourly_surface_pressure"
parameter_id = "surface_pressure"
locations = ["san_francisco", "phoenix", "chicago", "miami", "anchorage"]
series_defs = [
    {"series_id": "open_meteo_value_f32", "array_type": "f", "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
]
for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

group_values = defaultdict(list)
group_years = defaultdict(list)
group_months = defaultdict(list)
group_days = defaultdict(list)
group_hours = defaultdict(list)
stats_path = filtered_root / "location_year_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["location_id", "year", "row_count", "kept_count", "skipped_blank_count", "skipped_parse_count", "start_time", "end_time"])
    for location_id in locations:
        for year in range(2022, 2024):
            path = download_root / f"{location_id}_{year}.json"
            if not path.is_file():
                raise SystemExit(f"missing raw JSON: {path}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            hourly = payload.get("hourly", {})
            times = hourly.get("time")
            values = hourly.get(parameter_id)
            if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
                raise SystemExit(f"unexpected hourly payload in {path}")
            row_count = len(times)
            kept_count = 0
            skipped_blank_count = 0
            skipped_parse_count = 0
            start_time = ""
            end_time = ""
            for ts, raw_value in zip(times, values):
                if raw_value in ("", None):
                    skipped_blank_count += 1
                    continue
                try:
                    value = float(raw_value)
                    date_part, hour_part = str(ts).split("T", 1)
                    year_s, month_s, day_s = date_part.split("-")
                    hour_s = hour_part.split(":", 1)[0]
                    obs_year = int(year_s)
                    obs_month = int(month_s)
                    obs_day = int(day_s)
                    obs_hour = int(hour_s)
                except (TypeError, ValueError):
                    skipped_parse_count += 1
                    continue
                if obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31 or obs_hour < 0 or obs_hour > 23:
                    skipped_parse_count += 1
                    continue
                group_values[location_id].append(value)
                group_years[location_id].append(obs_year)
                group_months[location_id].append(obs_month)
                group_days[location_id].append(obs_day)
                group_hours[location_id].append(obs_hour)
                kept_count += 1
                if start_time == "":
                    start_time = str(ts)
                end_time = str(ts)
            writer.writerow([location_id, year, row_count, kept_count, skipped_blank_count, skipped_parse_count, start_time, end_time])

for location_id in sorted(group_values):
    payloads = {
        "open_meteo_value_f32": group_values[location_id],
    }
    for series in series_defs:
        payload = array.array(series["array_type"], payloads[series["series_id"]])
        if payload.itemsize > 1 and os.sys.byteorder != "little":
            payload.byteswap()
        out_path = samples_root / series["series_id"] / f"{location_id}.bin"
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
            "location_id": location_id,
            "parameter_id": parameter_id,
        })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
PY

say "built samples under ${SAMPLES_ROOT}"
