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
import math
import os
import shutil
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

if series_dir.exists():
    shutil.rmtree(series_dir)
series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

def parse_station(station: dict[str, str]) -> tuple[list[tuple[str, float]], dict[str, object]]:
    station_dir = download_root / station["family"]
    if not station_dir.is_dir():
        raise SystemExit(f"missing station raw directory: {station_dir}")
    by_timestamp: dict[str, float] = {}
    json_files = sorted(station_dir.glob("*.json"))
    if not json_files:
        raise SystemExit(f"no JSON files found in {station_dir}")

    raw_file_count = 0
    raw_row_count = 0
    duplicate_rows = 0
    for path in json_files:
        raw_file_count += 1
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
            if timestamp in by_timestamp:
                duplicate_rows += 1
                if by_timestamp[timestamp] != value:
                    raise SystemExit(f"{path} has conflicting duplicate timestamp {timestamp}")
            by_timestamp[timestamp] = value

    ordered = sorted(by_timestamp.items())
    values = [value for _, value in ordered]
    stats = {
        "station_id": station["station_id"],
        "station_slug": station["station_slug"],
        "station_name": station["station_name"],
        "row_count": len(values),
        "raw_file_count": raw_file_count,
        "raw_row_count": raw_row_count,
        "duplicate_rows": duplicate_rows,
        "first_timestamp_utc": ordered[0][0],
        "last_timestamp_utc": ordered[-1][0],
        "min_value": min(values),
        "max_value": max(values),
    }
    return ordered, stats

index_records: list[dict[str, object]] = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(
        [
            "station_id",
            "station_slug",
            "station_name",
            "row_count",
            "raw_file_count",
            "raw_row_count",
            "duplicate_rows",
            "first_timestamp_utc",
            "last_timestamp_utc",
            "min_value",
            "max_value",
        ]
    )

    for station in stations:
        ordered, stats = parse_station(station)
        payload = array.array("d", [value for _, value in ordered])
        if os.sys.byteorder != "little":
            payload.byteswap()
        out_path = series_dir / f"{station['station_slug']}.bin"
        with out_path.open("wb") as out_file:
            out_file.write(payload.tobytes())
        sample_size_bytes = out_path.stat().st_size
        writer.writerow(
            [
                stats["station_id"],
                stats["station_slug"],
                stats["station_name"],
                stats["row_count"],
                stats["raw_file_count"],
                stats["raw_row_count"],
                stats["duplicate_rows"],
                stats["first_timestamp_utc"],
                stats["last_timestamp_utc"],
                stats["min_value"],
                stats["max_value"],
            ]
        )
        index_records.append(
            {
                "dataset_id": dataset_id,
                "series_id": series_id,
                "sample_path": out_path.relative_to(data_root).as_posix(),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
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
