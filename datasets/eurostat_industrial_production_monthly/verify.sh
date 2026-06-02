#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="eurostat_industrial_production_monthly"
DOWNLOAD_ROOT="${DATA_DIR}/downloads/${DATASET_ID}"
FILTERED_ROOT="${DATA_DIR}/filtered/${DATASET_ID}"
INDEX_ROOT="${DATA_DIR}/index/${DATASET_ID}"
SAMPLES_ROOT="${DATA_DIR}/samples/${DATASET_ID}"
LOG_ROOT="${DATA_DIR}/logs/${DATASET_ID}"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/verify.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/verify.latest.log"

mkdir -p "${LOG_ROOT}"
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
import csv, json, os, re
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent
dataset_id = os.environ["DATASET_ID"]

countries = ["DE", "FR", "IT", "ES", "NL"]
series_defs = [
    {"series_id": "industrial_production_index_f32", "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4},
    {"series_id": "obs_year_u16", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
    {"series_id": "obs_month_u8", "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1},
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

stats_path = filtered_root / "country_stats.tsv"
index_path = index_root / "samples.jsonl"
failures_path = download_root / "download_failures.tsv"
if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

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

with stats_path.open("r", encoding="utf-8", newline="") as handle:
    stats_rows = list(csv.DictReader(handle, delimiter="\t"))
stats_by_country = {row["country_code"]: row for row in stats_rows}
expected_records = {}

for country_code in countries:
    if country_code not in geo_index:
        raise SystemExit(f"missing geo category {country_code}")
    row_count = len(time_items)
    kept_count = 0
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
            float(raw_value)
        except (TypeError, ValueError):
            skipped_parse += 1
            continue
        kept_count += 1
        period = f"{year:04d}-{month:02d}"
        if start_period == "":
            start_period = period
        end_period = period
    stats_row = stats_by_country.get(country_code)
    if stats_row is None:
        raise SystemExit(f"missing stats row for {country_code}")
    for field, expected in [("row_count", row_count), ("kept_count", kept_count), ("skipped_blank_count", skipped_blank), ("skipped_parse_count", skipped_parse)]:
        if int(stats_row[field]) != expected:
            raise SystemExit(f"stats mismatch for {country_code} field {field}: stats={stats_row[field]} raw={expected}")
    if stats_row["start_period"] != start_period or stats_row["end_period"] != end_period:
        raise SystemExit(f"period-range mismatch for {country_code}")
    for series in series_defs:
        sample_path = samples_root / series["series_id"] / f"{country_code.lower()}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = kept_count * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}")
        expected_records[(series["series_id"], country_code.lower())] = {
            "dataset_id": dataset_id,
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
            "sample_size_bytes": sample_size_bytes,
            "value_count": kept_count,
            "country_code": country_code,
        }

index_records = {}
with index_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        sample_path = record.get("sample_path")
        sample_key = Path(sample_path).stem if isinstance(sample_path, str) else ""
        key = (record.get("series_id"), sample_key)
        if key in index_records:
            raise SystemExit(f"duplicate index entry for {key} on line {line_number}")
        index_records[key] = record
if set(index_records) != set(expected_records):
    raise SystemExit(f"sample index keys do not match samples: index={len(index_records)} expected={len(expected_records)}")
for key, expected in expected_records.items():
    record = index_records[key]
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            raise SystemExit(f"index mismatch for {key} field {field}: {record.get(field)!r} != {expected_value!r}")
print("verified raw inventory, generated sample sizes, stats, and sample index")
PY

say "verified raw inventory, generated sample sizes, stats, and sample index"
