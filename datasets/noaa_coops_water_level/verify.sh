#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}

DOWNLOAD_ROOT="${DATA_DIR}/downloads/noaa_coops_water_level"
FILTERED_ROOT="${DATA_DIR}/filtered/noaa_coops_water_level"
INDEX_ROOT="${DATA_DIR}/index/noaa_coops_water_level"
SAMPLES_ROOT="${DATA_DIR}/samples/noaa_coops_water_level"
LOG_ROOT="${DATA_DIR}/logs/noaa_coops_water_level"
RUN_TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="${LOG_ROOT}/verify.${RUN_TS}.log"
LATEST_LOG="${LOG_ROOT}/verify.latest.log"

mkdir -p "${LOG_ROOT}"
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
import json
import math
import os
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

dataset_id = "noaa_coops_water_level"
series_id = "water_level_f64"
series_dir = samples_root / series_id
index_path = index_root / "samples.jsonl"
stats_path = filtered_root / "station_stats.tsv"
failures_path = download_root / "download_failures.tsv"

stations = [
    {
        "station_id": "9414290",
        "station_slug": "san_francisco",
        "station_name": "San Francisco, CA",
        "family": "noaa_coops_9414290_san_francisco",
    },
    {
        "station_id": "9447130",
        "station_slug": "seattle",
        "station_name": "Seattle, WA",
        "family": "noaa_coops_9447130_seattle",
    },
    {
        "station_id": "8518750",
        "station_slug": "the_battery",
        "station_name": "The Battery, NY",
        "family": "noaa_coops_8518750_the_battery",
    },
    {
        "station_id": "8443970",
        "station_slug": "boston",
        "station_name": "Boston, MA",
        "family": "noaa_coops_8443970_boston",
    },
    {
        "station_id": "8724580",
        "station_slug": "key_west",
        "station_name": "Key West, FL",
        "family": "noaa_coops_8724580_key_west",
    },
]

if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")

if not stats_path.is_file():
    raise SystemExit(f"missing station stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")
if not series_dir.is_dir():
    raise SystemExit(f"missing samples directory: {series_dir}")

with stats_path.open("r", encoding="utf-8", newline="") as handle:
    stats_rows = list(csv.DictReader(handle, delimiter="\t"))
stats_by_slug = {row["station_slug"]: row for row in stats_rows}

expected_records: dict[tuple[str, str], dict[str, object]] = {}

for station in stations:
    station_dir = download_root / station["family"]
    json_files = sorted(station_dir.glob("*.json"))
    if not json_files:
        raise SystemExit(f"missing JSON files in {station_dir}")
    timestamps: dict[str, float] = {}
    raw_row_count = 0
    duplicate_rows = 0
    for path in json_files:
        if path.stat().st_size <= 0:
            raise SystemExit(f"empty raw file: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "error" in payload:
            raise SystemExit(f"{path} contains API error payload: {payload['error']}")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise SystemExit(f"{path} is missing data[]")
        for row in rows:
            raw_row_count += 1
            timestamp = row.get("t")
            value_text = row.get("v")
            if timestamp in (None, "") or value_text in (None, ""):
                raise SystemExit(f"{path} has a row without timestamp or value")
            value = float(value_text)
            if not math.isfinite(value):
                raise SystemExit(f"{path} has non-finite value {value_text!r}")
            if timestamp in timestamps:
                duplicate_rows += 1
                if timestamps[timestamp] != value:
                    raise SystemExit(f"{path} has conflicting duplicate timestamp {timestamp}")
            timestamps[timestamp] = value

    ordered = sorted(timestamps.items())
    if not ordered:
        raise SystemExit(f"no values found for {station['station_slug']}")
    value_count = len(ordered)
    sample_path = series_dir / f"{station['station_slug']}.bin"
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    sample_size_bytes = sample_path.stat().st_size
    expected_size = value_count * 8
    if sample_size_bytes != expected_size:
        raise SystemExit(
            f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}"
        )

    stats_row = stats_by_slug.get(station["station_slug"])
    if stats_row is None:
        raise SystemExit(f"missing station stats row for {station['station_slug']}")
    if int(stats_row["row_count"]) != value_count:
        raise SystemExit(
            f"row count mismatch for {station['station_slug']}: stats={stats_row['row_count']} raw={value_count}"
        )
    if int(stats_row["raw_file_count"]) != len(json_files):
        raise SystemExit(
            f"raw file count mismatch for {station['station_slug']}: stats={stats_row['raw_file_count']} raw={len(json_files)}"
        )
    if int(stats_row["raw_row_count"]) != raw_row_count:
        raise SystemExit(
            f"raw row count mismatch for {station['station_slug']}: stats={stats_row['raw_row_count']} raw={raw_row_count}"
        )
    if int(stats_row["duplicate_rows"]) != duplicate_rows:
        raise SystemExit(
            f"duplicate row mismatch for {station['station_slug']}: stats={stats_row['duplicate_rows']} raw={duplicate_rows}"
        )

    expected_records[(series_id, station["station_slug"])] = {
        "dataset_id": dataset_id,
        "series_id": series_id,
        "sample_path": sample_path.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": sample_size_bytes,
        "value_count": value_count,
    }

index_records: dict[tuple[str, str], dict[str, object]] = {}
with index_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        sample_path = record.get("sample_path")
        slug = Path(sample_path).stem if isinstance(sample_path, str) else ""
        key = (record.get("series_id"), slug)
        if key in index_records:
            raise SystemExit(f"duplicate index entry for {key} on line {line_number}")
        index_records[key] = record

if set(index_records) != set(expected_records):
    raise SystemExit(
        f"sample index keys do not match samples: index={len(index_records)} expected={len(expected_records)}"
    )

for key, expected in expected_records.items():
    record = index_records[key]
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            raise SystemExit(
                f"index mismatch for {key} field {field}: {record.get(field)!r} != {expected_value!r}"
            )

print("verified raw inventory, generated sample sizes, and sample index")
PY

say "verified raw inventory, generated sample sizes, and sample index"
