#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}

DOWNLOAD_ROOT="${DATA_DIR}/downloads/usgs_nwis_streamflow_daily"
FILTERED_ROOT="${DATA_DIR}/filtered/usgs_nwis_streamflow_daily"
INDEX_ROOT="${DATA_DIR}/index/usgs_nwis_streamflow_daily"
SAMPLES_ROOT="${DATA_DIR}/samples/usgs_nwis_streamflow_daily"
LOG_ROOT="${DATA_DIR}/logs/usgs_nwis_streamflow_daily"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/build.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/build.latest.log"

mkdir -p "${FILTERED_ROOT}" "${INDEX_ROOT}" "${SAMPLES_ROOT}" "${LOG_ROOT}"
: > "${LOG_FILE}"
sync_latest_log() {
  cp "${LOG_FILE}" "${LATEST_LOG}"
}
trap sync_latest_log EXIT

say() {
  printf '%s\n' "$*" | tee -a "${LOG_FILE}"
}

say "download_root=${DOWNLOAD_ROOT}"
say "filtered_root=${FILTERED_ROOT}"
say "index_root=${INDEX_ROOT}"
say "samples_root=${SAMPLES_ROOT}"
say "log_file=${LOG_FILE}"

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" \
FILTERED_ROOT="${FILTERED_ROOT}" \
INDEX_ROOT="${INDEX_ROOT}" \
SAMPLES_ROOT="${SAMPLES_ROOT}" \
python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations

import array
import csv
import json
import os
import shutil
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "usgs_nwis_streamflow_daily"
site_ids = [
    "01646500",
    "07374000",
    "08158000",
    "09380000",
]
series_defs = [
    {"series_id": "usgs_discharge_cfs_f64", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "obs_year_u16", "array_type": "H", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_month_u8", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
    {"series_id": "obs_day_u8", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
]

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)

filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "site_year_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records: list[dict[str, object]] = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["site_id", "year", "row_count", "value_count", "skipped_count", "start_date", "end_date", "series_name"])

    for site_id in site_ids:
        discharge_values: list[float] = []
        year_values: list[int] = []
        month_values: list[int] = []
        day_values: list[int] = []

        for year in range(2021, 2024):
            json_path = download_root / f"dv_{site_id}_{year}.json"
            if not json_path.is_file():
                raise SystemExit(f"missing raw JSON: {json_path}")

            with json_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)

            time_series = payload.get("value", {}).get("timeSeries", [])
            if not time_series:
                raise SystemExit(f"no timeSeries data in {json_path}")
            selected_series = None
            for candidate in time_series:
                name = str(candidate.get("name", ""))
                if name.endswith(":00003"):
                    selected_series = candidate
                    break
            if selected_series is None:
                selected_series = time_series[0]

            values_wrappers = selected_series.get("values", [])
            if not values_wrappers:
                raise SystemExit(f"no values data in {json_path}")
            rows = values_wrappers[0].get("value", [])
            if not isinstance(rows, list):
                raise SystemExit(f"unexpected values payload in {json_path}")

            row_count = len(rows)
            value_count = 0
            skipped_count = 0
            first_date = ""
            last_date = ""

            for row in rows:
                raw_value = str(row.get("value", "")).strip()
                raw_date = str(row.get("dateTime", "")).strip()
                if raw_value == "" or raw_date == "":
                    skipped_count += 1
                    continue
                try:
                    discharge = float(raw_value)
                except ValueError:
                    skipped_count += 1
                    continue
                date_part = raw_date[:10]
                pieces = date_part.split("-")
                if len(pieces) != 3:
                    skipped_count += 1
                    continue
                try:
                    obs_year = int(pieces[0])
                    obs_month = int(pieces[1])
                    obs_day = int(pieces[2])
                except ValueError:
                    skipped_count += 1
                    continue
                if obs_year < 0 or obs_year > 65535 or obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31:
                    skipped_count += 1
                    continue

                discharge_values.append(discharge)
                year_values.append(obs_year)
                month_values.append(obs_month)
                day_values.append(obs_day)
                value_count += 1
                if first_date == "":
                    first_date = date_part
                last_date = date_part

            writer.writerow([site_id, year, row_count, value_count, skipped_count, first_date, last_date, selected_series.get("name", "")])

        site_slug = f"site_{site_id}"
        values_by_series = {
            "usgs_discharge_cfs_f64": discharge_values,
            "obs_year_u16": year_values,
            "obs_month_u8": month_values,
            "obs_day_u8": day_values,
        }

        for series in series_defs:
            payload = array.array(series["array_type"], values_by_series[series["series_id"]])
            if payload.itemsize > 1 and os.sys.byteorder != "little":
                payload.byteswap()

            out_path = samples_root / series["series_id"] / f"{site_slug}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(payload.tobytes())
            sample_size_bytes = out_path.stat().st_size

            index_records.append(
                {
                    "dataset_id": dataset_id,
                    "series_id": series["series_id"],
                    "sample_path": out_path.relative_to(data_root).as_posix(),
                    "numeric_kind": series["numeric_kind"],
                    "bit_width": series["bit_width"],
                    "endianness": series["endianness"],
                    "element_size_bytes": series["element_size_bytes"],
                    "sample_size_bytes": sample_size_bytes,
                    "value_count": len(values_by_series[series["series_id"]]),
                }
            )

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
PY

say "built samples under ${SAMPLES_ROOT}"
