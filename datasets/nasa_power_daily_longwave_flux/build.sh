#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
START_YEAR=${NASA_POWER_DAILY_LONGWAVE_FLUX_START_YEAR:-1988}
END_YEAR=${NASA_POWER_DAILY_LONGWAVE_FLUX_END_YEAR:-2024}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/nasa_power_daily_longwave_flux"
FILTERED_ROOT="${DATA_DIR}/filtered/nasa_power_daily_longwave_flux"
INDEX_ROOT="${DATA_DIR}/index/nasa_power_daily_longwave_flux"
SAMPLES_ROOT="${DATA_DIR}/samples/nasa_power_daily_longwave_flux"
LOG_ROOT="${DATA_DIR}/logs/nasa_power_daily_longwave_flux"
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
say "year_window=${START_YEAR}..${END_YEAR}"

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" FILTERED_ROOT="${FILTERED_ROOT}" INDEX_ROOT="${INDEX_ROOT}" SAMPLES_ROOT="${SAMPLES_ROOT}" START_YEAR="${START_YEAR}" END_YEAR="${END_YEAR}" python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import array
import csv
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
start_year = int(os.environ["START_YEAR"])
end_year = int(os.environ["END_YEAR"])

dataset_id = "nasa_power_daily_longwave_flux"
locations = [
    "san_francisco",
    "phoenix",
    "chicago",
    "miami",
    "anchorage",
    "fairbanks",
    "honolulu",
    "denver",
    "new_orleans",
    "san_juan",
    "seattle",
    "boston",
    "atlanta",
    "dallas",
    "minneapolis",
    "las_vegas",
    "albuquerque",
    "portland",
    "billings",
    "fargo",
]
parameter_series = {
    "ALLSKY_SFC_LW_DWN": {"series_id": "nasa_power_longwave_allsky_lw_down_f64", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    "CLRSKY_SFC_LW_DWN": {"series_id": "nasa_power_longwave_clrsky_lw_down_f64", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
}
parameter_ids = list(parameter_series)
series_defs = list(parameter_series.values())

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

group_values = defaultdict(list)
stats_path = filtered_root / "location_parameter_year_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["location_id", "parameter_id", "year", "row_count", "kept_count", "skipped_fill_count", "skipped_parse_count", "start_date", "end_date"])
    for location_id in locations:
        for year in range(start_year, end_year + 1):
            path = download_root / f"{location_id}_{year}.json"
            if not path.is_file():
                raise SystemExit(f"missing raw JSON: {path}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            header = payload.get("header", {})
            fill_value = header.get("fill_value")
            parameter_block = payload.get("properties", {}).get("parameter", {})
            if not isinstance(parameter_block, dict):
                raise SystemExit(f"unexpected parameter payload in {path}")
            for parameter_id in parameter_ids:
                values = parameter_block.get(parameter_id)
                if not isinstance(values, dict):
                    raise SystemExit(f"missing parameter {parameter_id} in {path}")
                row_count = len(values)
                kept_count = 0
                skipped_fill_count = 0
                skipped_parse_count = 0
                start_date = ""
                end_date = ""
                for date_key in sorted(values):
                    raw_value = values[date_key]
                    if len(date_key) != 8 or not date_key.isdigit():
                        skipped_parse_count += 1
                        continue
                    if raw_value == fill_value:
                        skipped_fill_count += 1
                        continue
                    if isinstance(raw_value, str) and raw_value.strip().upper() in {"", "NAN"}:
                        skipped_parse_count += 1
                        continue
                    try:
                        value = float(raw_value)
                        obs_month = int(date_key[4:6])
                        obs_day = int(date_key[6:8])
                    except (TypeError, ValueError):
                        skipped_parse_count += 1
                        continue
                    if obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31:
                        skipped_parse_count += 1
                        continue
                    group_values[(location_id, parameter_id)].append(value)
                    kept_count += 1
                    if start_date == "":
                        start_date = date_key
                    end_date = date_key
                writer.writerow([location_id, parameter_id, year, row_count, kept_count, skipped_fill_count, skipped_parse_count, start_date, end_date])

for location_id, parameter_id in sorted(group_values):
    series = parameter_series[parameter_id]
    payload = array.array(series["array_type"], group_values[(location_id, parameter_id)])
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
        "value_count": len(group_values[(location_id, parameter_id)]),
        "location_id": location_id,
        "parameter_id": parameter_id,
        "sample_geometry": "daily_point_time_series",
        "sample_rank": 1,
        "sample_axes": ["day"],
    })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True) + "\n")
PY

say "built samples under ${SAMPLES_ROOT}"
