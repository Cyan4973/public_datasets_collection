#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DOWNLOAD_ROOT="${DATA_DIR}/downloads/world_bank_population_total"
FILTERED_ROOT="${DATA_DIR}/filtered/world_bank_population_total"
INDEX_ROOT="${DATA_DIR}/index/world_bank_population_total"
SAMPLES_ROOT="${DATA_DIR}/samples/world_bank_population_total"
LOG_ROOT="${DATA_DIR}/logs/world_bank_population_total"
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
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "world_bank_population_total"
indicator_id = "SP.POP.TOTL"
countries = ["USA", "CHN", "IND", "BRA", "DEU", "JPN", "NGA", "MEX", "FRA", "ZAF"]
series_defs = [
    {"series_id": "world_bank_value_f64", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "obs_year_u16", "array_type": "H", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
]
for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "country_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["country_code", "row_count", "kept_count", "skipped_null_count", "skipped_parse_count", "start_year", "end_year"])
    for country_code in countries:
        path = download_root / f"{country_code}.json"
        if not path.is_file():
            raise SystemExit(f"missing raw JSON: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload[1]
        row_count = len(rows)
        kept_count = 0
        skipped_null_count = 0
        skipped_parse_count = 0
        start_year = ""
        end_year = ""
        values = []
        years = []
        parsed = []
        for row in rows:
            raw_value = row.get("value")
            raw_year = row.get("date")
            if raw_value in ("", None):
                skipped_null_count += 1
                continue
            try:
                value = float(raw_value)
                year = int(str(raw_year))
            except (TypeError, ValueError):
                skipped_parse_count += 1
                continue
            if year < 1900 or year > 2100:
                skipped_parse_count += 1
                continue
            parsed.append((year, value))
        parsed.sort()
        for year, value in parsed:
            values.append(value)
            years.append(year)
            kept_count += 1
            if start_year == "":
                start_year = str(year)
            end_year = str(year)
        payloads = {"world_bank_value_f64": values, "obs_year_u16": years}
        for series in series_defs:
            payload = array.array(series["array_type"], payloads[series["series_id"]])
            if payload.itemsize > 1 and os.sys.byteorder != "little":
                payload.byteswap()
            out_path = samples_root / series["series_id"] / f"{country_code}.bin"
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
                "country_code": country_code,
                "indicator_id": indicator_id,
            })
        writer.writerow([country_code, row_count, kept_count, skipped_null_count, skipped_parse_count, start_year, end_year])

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
PY

say "built samples under ${SAMPLES_ROOT}"
