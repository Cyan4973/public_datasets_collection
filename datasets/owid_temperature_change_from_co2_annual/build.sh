#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/owid_temperature_change_from_co2_annual"
FILTERED_ROOT="${DATA_DIR}/filtered/owid_temperature_change_from_co2_annual"
INDEX_ROOT="${DATA_DIR}/index/owid_temperature_change_from_co2_annual"
SAMPLES_ROOT="${DATA_DIR}/samples/owid_temperature_change_from_co2_annual"
LOG_ROOT="${DATA_DIR}/logs/owid_temperature_change_from_co2_annual"
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

dataset_id = "owid_temperature_change_from_co2_annual"
target_column = "temperature_change_from_co2"
countries = ["USA", "CHN", "IND", "BRA", "DEU", "JPN", "NGA", "MEX", "FRA", "ZAF"]
series_defs = [
    {"series_id": "owid_value_f32", "array_type": "f", "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
]
for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

path = download_root / "owid-co2-data.csv"
if not path.is_file():
    raise SystemExit(f"missing raw CSV: {path}")

stats_path = filtered_root / "country_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []
rows_by_country = defaultdict(list)
country_names = {}
with path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
        iso = str(row.get("iso_code", "")).strip()
        if iso not in countries:
            continue
        rows_by_country[iso].append(row)
        country_names.setdefault(iso, str(row.get("country", iso)).strip() or iso)

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["country_code", "row_count", "kept_count", "skipped_blank_count", "skipped_parse_count", "start_year", "end_year"])
    for country_code in countries:
        values = []
        years = []
        row_count = len(rows_by_country[country_code])
        skipped_blank = 0
        skipped_parse = 0
        start_year = ""
        end_year = ""
        parsed = []
        for row in rows_by_country[country_code]:
            raw_year = str(row.get("year", "")).strip()
            raw_value = str(row.get(target_column, "")).strip()
            if raw_year == "" or raw_value == "":
                skipped_blank += 1
                continue
            try:
                year = int(raw_year)
                value = float(raw_value)
            except ValueError:
                skipped_parse += 1
                continue
            if year < 1800 or year > 2100:
                skipped_parse += 1
                continue
            parsed.append((year, value))
        parsed.sort()
        for year, value in parsed:
            values.append(value)
            years.append(year)
            if start_year == "":
                start_year = str(year)
            end_year = str(year)
        writer.writerow([country_code, row_count, len(values), skipped_blank, skipped_parse, start_year, end_year])
        payloads = {"owid_value_f32": values}
        country_name = country_names.get(country_code, country_code)
        for series in series_defs:
            payload = array.array(series["array_type"], payloads[series["series_id"]])
            if payload.itemsize > 1 and os.sys.byteorder != "little":
                payload.byteswap()
            out_path = samples_root / series["series_id"] / f"{country_code}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(payload.tobytes())
            index_records.append({
                "dataset_id": dataset_id,
                "series_id": series["series_id"],
                "sample_path": out_path.relative_to(data_root).as_posix(),
                "numeric_kind": series["numeric_kind"],
                "bit_width": series["bit_width"],
                "endianness": series["endianness"],
                "element_size_bytes": series["element_size_bytes"],
                "sample_size_bytes": out_path.stat().st_size,
                "value_count": len(payloads[series["series_id"]]),
                "country_code": country_code,
                "country_name": country_name,
                "owid_column": target_column,
            })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
if not index_records:
    raise SystemExit("no country samples were produced")
PY

say "built samples under ${SAMPLES_ROOT}"
