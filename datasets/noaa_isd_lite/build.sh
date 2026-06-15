#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}

DOWNLOAD_ROOT="${DATA_DIR}/downloads/noaa_isd_lite"
FILTERED_ROOT="${DATA_DIR}/filtered/noaa_isd_lite"
INDEX_ROOT="${DATA_DIR}/index/noaa_isd_lite"
SAMPLES_ROOT="${DATA_DIR}/samples/noaa_isd_lite"
LOG_ROOT="${DATA_DIR}/logs/noaa_isd_lite"
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

import csv
import gzip
import json
import os
import shutil
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])

dataset_root = samples_root.parent.parent
index_root.mkdir(parents=True, exist_ok=True)
index_path = index_root / "samples.jsonl"

years = [2021, 2022, 2023]
stations = [
    ("486980-99999", "singapore"),
    ("967490-99999", "jakarta"),
    ("486470-99999", "kuala_lumpur"),
    ("821110-99999", "manaus"),
    ("637400-99999", "nairobi"),
    ("430030-99999", "mumbai"),
    ("484560-99999", "bangkok"),
    ("652010-99999", "lagos"),
    ("911820-22521", "honolulu"),
    ("941200-99999", "darwin"),
    ("411940-99999", "dubai"),
    ("412170-99999", "abu_dhabi"),
    ("722780-23183", "phoenix"),
    ("623660-99999", "cairo"),
    ("943260-99999", "alice_springs"),
    ("725650-03017", "denver"),
    ("442920-99999", "ulaanbaatar"),
    ("846280-99999", "lima"),
    ("037720-99999", "london"),
    ("071570-99999", "paris"),
    ("476710-99999", "tokyo"),
    ("947670-99999", "sydney"),
    ("875760-99999", "buenos_aires"),
    ("837800-99999", "sao_paulo"),
    ("162420-99999", "rome"),
    ("688160-99999", "cape_town"),
    ("724940-23234", "san_francisco"),
    ("722190-13874", "atlanta"),
    ("583620-99999", "shanghai"),
    ("931190-99999", "auckland"),
    ("725300-94846", "chicago"),
    ("716240-99999", "toronto"),
    ("276120-99999", "moscow"),
    ("545110-99999", "beijing"),
    ("471080-99999", "seoul"),
    ("029740-99999", "helsinki"),
    ("024840-99999", "stockholm"),
    ("726580-14922", "minneapolis"),
    ("123750-99999", "warsaw"),
    ("296340-99999", "novosibirsk"),
    ("474120-99999", "sapporo"),
    ("702730-26451", "anchorage"),
    ("702610-26411", "fairbanks"),
    ("040300-99999", "reykjavik"),
    ("012250-99999", "tromso"),
    ("249590-99999", "yakutsk"),
]

series_defs = [
    ("isd_year", "H", 2, "uint", 16, "little"),
    ("isd_month", "B", 1, "uint", 8, "little"),
    ("isd_day", "B", 1, "uint", 8, "little"),
    ("isd_hour", "B", 1, "uint", 8, "little"),
    ("isd_temp", "h", 2, "int", 16, "little"),
    ("isd_dewp", "h", 2, "int", 16, "little"),
    ("isd_slp", "h", 2, "int", 16, "little"),
    ("isd_wdir", "h", 2, "int", 16, "little"),
    ("isd_wspd", "h", 2, "int", 16, "little"),
    ("isd_sky", "h", 2, "int", 16, "little"),
    ("isd_precip1h", "h", 2, "int", 16, "little"),
    ("isd_precip6h", "h", 2, "int", 16, "little"),
]

series_meta = {
    series_id: {
        "element_size_bytes": element_size,
        "numeric_kind": numeric_kind,
        "bit_width": bit_width,
        "endianness": endianness,
    }
    for series_id, _, element_size, numeric_kind, bit_width, endianness in series_defs
}

import array

for series_id, _, _, _, _, _ in series_defs:
    out_dir = samples_root / series_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

filtered_root.mkdir(parents=True, exist_ok=True)
row_counts_path = filtered_root / "station_row_counts.tsv"
skipped_constants_path = filtered_root / "skipped_constant_samples.tsv"
index_records: list[dict[str, object]] = []

def parse_row(line: str) -> tuple[int, ...] | None:
    parts = line.strip().split()
    if len(parts) != 12:
        return None
    try:
        values = tuple(int(part) for part in parts)
    except ValueError:
        return None
    year, month, day, hour = values[:4]
    if not (0 <= month <= 12 and 0 <= day <= 31 and 0 <= hour <= 23):
        return None
    return values

def is_constant(values) -> bool:
    return bool(values) and all(value == values[0] for value in values)

with row_counts_path.open("w", encoding="ascii", newline="") as tsv_file, skipped_constants_path.open("w", encoding="ascii", newline="") as skipped_file:
    writer = csv.writer(tsv_file, delimiter="\t")
    skipped_writer = csv.writer(skipped_file, delimiter="\t")
    writer.writerow(["station_id", "station_slug", "row_count"])
    skipped_writer.writerow(["station_id", "station_slug", "series_id", "value_count", "constant_value"])

    for station_id, slug in stations:
        arrays = {
            "isd_year": array.array("H"),
            "isd_month": array.array("B"),
            "isd_day": array.array("B"),
            "isd_hour": array.array("B"),
            "isd_temp": array.array("h"),
            "isd_dewp": array.array("h"),
            "isd_slp": array.array("h"),
            "isd_wdir": array.array("h"),
            "isd_wspd": array.array("h"),
            "isd_sky": array.array("h"),
            "isd_precip1h": array.array("h"),
            "isd_precip6h": array.array("h"),
        }

        row_count = 0
        for year in years:
            gz_path = download_root / "isd-lite" / str(year) / f"{station_id}-{year}.gz"
            if not gz_path.is_file():
                raise SystemExit(f"missing raw file: {gz_path}")
            with gzip.open(gz_path, "rt", encoding="ascii", errors="strict") as handle:
                for line in handle:
                    parsed = parse_row(line)
                    if parsed is None:
                        continue
                    (
                        year_v,
                        month_v,
                        day_v,
                        hour_v,
                        temp_v,
                        dewp_v,
                        slp_v,
                        wdir_v,
                        wspd_v,
                        sky_v,
                        precip1h_v,
                        precip6h_v,
                    ) = parsed

                    arrays["isd_year"].append(year_v)
                    arrays["isd_month"].append(month_v)
                    arrays["isd_day"].append(day_v)
                    arrays["isd_hour"].append(hour_v)
                    arrays["isd_temp"].append(temp_v)
                    arrays["isd_dewp"].append(dewp_v)
                    arrays["isd_slp"].append(slp_v)
                    arrays["isd_wdir"].append(wdir_v)
                    arrays["isd_wspd"].append(wspd_v)
                    arrays["isd_sky"].append(sky_v)
                    arrays["isd_precip1h"].append(precip1h_v)
                    arrays["isd_precip6h"].append(precip6h_v)
                    row_count += 1

        writer.writerow([station_id, slug, row_count])

        for series_id, _, _, _, _, _ in series_defs:
            out_path = samples_root / series_id / f"{slug}.bin"
            payload = arrays[series_id]
            if is_constant(payload):
                skipped_writer.writerow([station_id, slug, series_id, len(payload), payload[0]])
                continue
            if payload.itemsize > 1 and os.sys.byteorder != "little":
                payload.byteswap()
            with out_path.open("wb") as out_file:
                out_file.write(payload.tobytes())
            sample_size_bytes = out_path.stat().st_size
            index_records.append(
                {
                    "dataset_id": "noaa_isd_lite",
                    "series_id": series_id,
                    "sample_path": out_path.relative_to(dataset_root).as_posix(),
                    "numeric_kind": series_meta[series_id]["numeric_kind"],
                    "bit_width": series_meta[series_id]["bit_width"],
                    "endianness": series_meta[series_id]["endianness"],
                    "element_size_bytes": series_meta[series_id]["element_size_bytes"],
                    "sample_size_bytes": sample_size_bytes,
                    "value_count": len(payload),
                }
            )

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
PY

say "built samples under ${SAMPLES_ROOT}"
