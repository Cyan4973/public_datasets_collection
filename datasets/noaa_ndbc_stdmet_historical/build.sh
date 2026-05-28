#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}

DOWNLOAD_ROOT="${DATA_DIR}/downloads/noaa_ndbc_stdmet_historical"
FILTERED_ROOT="${DATA_DIR}/filtered/noaa_ndbc_stdmet_historical"
INDEX_ROOT="${DATA_DIR}/index/noaa_ndbc_stdmet_historical"
SAMPLES_ROOT="${DATA_DIR}/samples/noaa_ndbc_stdmet_historical"
LOG_ROOT="${DATA_DIR}/logs/noaa_ndbc_stdmet_historical"
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
import gzip
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

dataset_id = "noaa_ndbc_stdmet_historical"
station_ids = ["41009", "44013", "46042", "51001"]
element_ids = ["WDIR", "WSPD", "GST", "WVHT", "PRES", "ATMP", "WTMP"]
series_defs = [
    {"series_id": "ndbc_value_f64", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "obs_year_u16", "array_type": "H", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_month_u8", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
    {"series_id": "obs_day_u8", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
    {"series_id": "obs_hour_u8", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
]

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)

filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

group_values: dict[tuple[str, str], list[int | float]] = defaultdict(list)
group_years: dict[tuple[str, str], list[int]] = defaultdict(list)
group_months: dict[tuple[str, str], list[int]] = defaultdict(list)
group_days: dict[tuple[str, str], list[int]] = defaultdict(list)
group_hours: dict[tuple[str, str], list[int]] = defaultdict(list)

stats_path = filtered_root / "station_element_year_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records: list[dict[str, object]] = []


def normalize_header_tokens(tokens: list[str]) -> list[str]:
    return [token.lstrip("#").upper() for token in tokens]


with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(
        [
            "station_id",
            "element_id",
            "year",
            "row_count",
            "kept_count",
            "skipped_missing_count",
            "skipped_parse_count",
            "start_date",
            "end_date",
        ]
    )

    for station_id in station_ids:
        per_group_year = {
            (element_id, year): {
                "row_count": 0,
                "kept_count": 0,
                "skipped_missing_count": 0,
                "skipped_parse_count": 0,
                "start_date": "",
                "end_date": "",
            }
            for element_id in element_ids
            for year in range(2019, 2024)
        }

        for year in range(2019, 2024):
            path = download_root / f"{station_id}h{year}.txt.gz"
            if not path.is_file():
                raise SystemExit(f"missing raw file: {path}")

            header_tokens: list[str] | None = None
            with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    tokens = line.split()
                    first = tokens[0].lstrip("#").upper()
                    if first in {"YY", "YYYY"}:
                        header_tokens = normalize_header_tokens(tokens)
                        continue
                    if header_tokens is None:
                        continue
                    if first in {"YR", "YYYY", "YY"}:
                        continue

                    header_map = {name: idx for idx, name in enumerate(header_tokens)}
                    year_col = "YYYY" if "YYYY" in header_map else "YY" if "YY" in header_map else None
                    if year_col is None:
                        raise SystemExit(f"missing year column in {path}")
                    required_date_cols = [year_col, "MM", "DD", "HH"]
                    if not all(col in header_map for col in required_date_cols):
                        raise SystemExit(f"missing date columns in {path}")

                    try:
                        obs_year = int(tokens[header_map[year_col]])
                        if year_col == "YY":
                            obs_year += 1900 if obs_year >= 70 else 2000
                        obs_month = int(tokens[header_map["MM"]])
                        obs_day = int(tokens[header_map["DD"]])
                        obs_hour = int(tokens[header_map["HH"]])
                    except (ValueError, IndexError):
                        for element_id in element_ids:
                            per_group_year[(element_id, year)]["skipped_parse_count"] += 1
                        continue

                    date_value = f"{obs_year:04d}{obs_month:02d}{obs_day:02d}{obs_hour:02d}"
                    for element_id in element_ids:
                        if element_id not in header_map:
                            continue
                        bucket = per_group_year[(element_id, year)]
                        bucket["row_count"] += 1
                        try:
                            raw_value = tokens[header_map[element_id]]
                        except IndexError:
                            bucket["skipped_parse_count"] += 1
                            continue
                        if raw_value.upper() == "MM":
                            bucket["skipped_missing_count"] += 1
                            continue
                        try:
                            value = float(raw_value)
                        except ValueError:
                            bucket["skipped_parse_count"] += 1
                            continue
                        if obs_month < 1 or obs_month > 12 or obs_day < 1 or obs_day > 31 or obs_hour < 0 or obs_hour > 23:
                            bucket["skipped_parse_count"] += 1
                            continue

                        key = (station_id, element_id)
                        group_values[key].append(value)
                        group_years[key].append(obs_year)
                        group_months[key].append(obs_month)
                        group_days[key].append(obs_day)
                        group_hours[key].append(obs_hour)
                        bucket["kept_count"] += 1
                        if bucket["start_date"] == "":
                            bucket["start_date"] = date_value
                        bucket["end_date"] = date_value

        for element_id in element_ids:
            for year in range(2019, 2024):
                bucket = per_group_year[(element_id, year)]
                writer.writerow(
                    [
                        station_id,
                        element_id,
                        year,
                        bucket["row_count"],
                        bucket["kept_count"],
                        bucket["skipped_missing_count"],
                        bucket["skipped_parse_count"],
                        bucket["start_date"],
                        bucket["end_date"],
                    ]
                )

for key in sorted(group_values):
    station_id, element_id = key
    sample_slug = f"{station_id}_{element_id}"
    payloads = {
        "ndbc_value_f64": group_values[key],
        "obs_year_u16": group_years[key],
        "obs_month_u8": group_months[key],
        "obs_day_u8": group_days[key],
        "obs_hour_u8": group_hours[key],
    }

    for series in series_defs:
        payload = array.array(series["array_type"], payloads[series["series_id"]])
        if payload.itemsize > 1 and os.sys.byteorder != "little":
            payload.byteswap()

        out_path = samples_root / series["series_id"] / f"{sample_slug}.bin"
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
                "value_count": len(payloads[series["series_id"]]),
                "station_id": station_id,
                "element_id": element_id,
            }
        )

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
PY

say "built samples under ${SAMPLES_ROOT}"
