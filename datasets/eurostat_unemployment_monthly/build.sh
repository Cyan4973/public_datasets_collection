#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="eurostat_unemployment_monthly"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
FILTERED_ROOT="${DATA_DIR}/filtered/${DATASET_ID}"
INDEX_ROOT="${DATA_DIR}/index/${DATASET_ID}"
SAMPLES_ROOT="${DATA_DIR}/samples/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
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

DATASET_ID="${DATASET_ID}" DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" FILTERED_ROOT="${FILTERED_ROOT}" INDEX_ROOT="${INDEX_ROOT}" SAMPLES_ROOT="${SAMPLES_ROOT}" python3 - <<'PY' >>"${LOG_FILE}" 2>&1
from __future__ import annotations
import array, csv, json, os, re, shutil
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
dataset_id = os.environ["DATASET_ID"]

countries = ["DE", "FR", "IT", "ES", "NL"]
series_defs = [
    {"series_id": "unemployment_rate_f32", "array_type": "f", "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
    {"series_id": "obs_year_u16", "array_type": "H", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_month_u8", "array_type": "B", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
]

def parse_time_key(raw: str) -> tuple[int, int]:
    raw = raw.strip()
    match = re.fullmatch(r"(\d{4})[-M](\d{2})", raw)
    if not match:
        raise ValueError(raw)
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        raise ValueError(raw)
    return year, month

def flatten_index(ids, sizes, positions):
    index = 0
    stride = 1
    for dim_name, dim_size in zip(reversed(ids), reversed(sizes)):
        index += positions[dim_name] * stride
        stride *= dim_size
    return index

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

raw_path = download_root / "data.json"
if not raw_path.is_file():
    raise SystemExit(f"missing raw JSON: {raw_path}")
payload = json.loads(raw_path.read_text(encoding="utf-8"))
ids = payload["id"]
sizes = payload["size"]
dimension = payload["dimension"]
value_data = payload["value"]
geo_index = dimension["geo"]["category"]["index"]
time_index = dimension["time"]["category"]["index"]
time_items = sorted(time_index.items(), key=lambda item: item[1])

stats_path = filtered_root / "country_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["country_code", "row_count", "kept_count", "skipped_blank_count", "skipped_parse_count", "start_period", "end_period"])
    for country_code in countries:
        if country_code not in geo_index:
            raise SystemExit(f"missing geo category {country_code}")
        values = []
        years = []
        months = []
        row_count = len(time_items)
        skipped_blank = 0
        skipped_parse = 0
        start_period = ""
        end_period = ""
        for time_key, time_pos in time_items:
            positions = {}
            for dim_name in ids:
                if dim_name == "geo":
                    positions[dim_name] = geo_index[country_code]
                elif dim_name == "time":
                    positions[dim_name] = time_pos
                else:
                    positions[dim_name] = 0
            flat_index = flatten_index(ids, sizes, positions)
            if isinstance(value_data, dict):
                raw_value = value_data.get(str(flat_index))
            else:
                raw_value = value_data[flat_index] if flat_index < len(value_data) else None
            if raw_value in ("", None):
                skipped_blank += 1
                continue
            try:
                year, month = parse_time_key(time_key)
                value = float(raw_value)
            except (TypeError, ValueError):
                skipped_parse += 1
                continue
            values.append(value)
            years.append(year)
            months.append(month)
            period = f"{year:04d}-{month:02d}"
            if start_period == "":
                start_period = period
            end_period = period
        writer.writerow([country_code, row_count, len(values), skipped_blank, skipped_parse, start_period, end_period])
        payloads = {
            "unemployment_rate_f32": values,
            "obs_year_u16": years,
            "obs_month_u8": months,
        }
        for series in series_defs:
            payload_array = array.array(series["array_type"], payloads[series["series_id"]])
            if payload_array.itemsize > 1 and os.sys.byteorder != "little":
                payload_array.byteswap()
            out_path = samples_root / series["series_id"] / f"{country_code.lower()}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(payload_array.tobytes())
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
            })

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
if not index_records:
    raise SystemExit("no country samples were produced")
PY

say "built samples under ${SAMPLES_ROOT}"
