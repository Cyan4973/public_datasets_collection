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
import re
import shutil
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "usgs_nwis_streamflow_daily"

series_defs = [
    {"series_id": "usgs_discharge_cfs_f64", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "obs_year_u16", "array_type": "H", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
]

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)

filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

pat = re.compile(r"^dv_(\d+)_(\d{4})\.json$")
site_years: dict[str, list[int]] = {}
for f in sorted(download_root.glob("dv_*_*.json")):
    m = pat.match(f.name)
    if not m:
        continue
    site_id, year = m.group(1), int(m.group(2))
    site_years.setdefault(site_id, []).append(year)

stats_path = filtered_root / "site_year_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records: list[dict[str, object]] = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["site_id", "year", "row_count", "value_count", "skipped_count", "start_date", "end_date", "series_name"])

    for site_id in sorted(site_years):
        discharge_values: list[float] = []
        year_values: list[int] = []

        for year in sorted(site_years[site_id]):
            json_path = download_root / f"dv_{site_id}_{year}.json"
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            time_series = payload.get("value", {}).get("timeSeries", [])
            if not time_series:
                print(f"no timeSeries in {json_path.name}, skipping year", flush=True)
                continue
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
                print(f"no values in {json_path.name}, skipping year", flush=True)
                continue
            rows = None
            for wrapper in values_wrappers:
                candidate = wrapper.get("value", [])
                if isinstance(candidate, list) and candidate:
                    rows = candidate
                    break
            if rows is None:
                print(f"no non-empty value wrapper in {json_path.name}, skipping year", flush=True)
                continue

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
                value_count += 1
                if first_date == "":
                    first_date = date_part
                last_date = date_part

            writer.writerow([site_id, year, row_count, value_count, skipped_count, first_date, last_date, selected_series.get("name", "")])

        if not discharge_values:
            print(f"site {site_id}: no usable values, skipping sample output", flush=True)
            continue

        site_slug = f"site_{site_id}"
        values_by_series = {
            "usgs_discharge_cfs_f64": discharge_values,
            "obs_year_u16": year_values,
        }

        for series in series_defs:
            arr = array.array(series["array_type"], values_by_series[series["series_id"]])
            if arr.itemsize > 1 and os.sys.byteorder != "little":
                arr.byteswap()
            out_path = samples_root / series["series_id"] / f"{site_slug}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(arr.tobytes())
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

samples_written = sum(1 for r in index_records if r["series_id"] == "usgs_discharge_cfs_f64")
print(f"wrote samples for {samples_written} sites", flush=True)
PY

say "built samples under ${SAMPLES_ROOT}"
