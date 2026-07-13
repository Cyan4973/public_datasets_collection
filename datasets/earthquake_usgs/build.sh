#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}

DOWNLOAD_ROOT="${DATA_DIR}/downloads/earthquake_usgs"
FILTERED_ROOT="${DATA_DIR}/filtered/earthquake_usgs"
INDEX_ROOT="${DATA_DIR}/index/earthquake_usgs"
SAMPLES_ROOT="${DATA_DIR}/samples/earthquake_usgs"
LOG_ROOT="${DATA_DIR}/logs/earthquake_usgs"
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

dataset_id = "earthquake_usgs"
series_defs = [
    {"series_id": "eq_depth_f64", "column": "depth", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "eq_mag_f64", "column": "mag", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "eq_gap_f64", "column": "gap", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "eq_dmin_f64", "column": "dmin", "array_type": "d", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "eq_nst_u16", "column": "nst", "array_type": "H", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
]

for series in series_defs:
    series_dir = samples_root / series["series_id"]
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True, exist_ok=True)

filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "year_series_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records: list[dict[str, object]] = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow(["year", "series_id", "row_count", "value_count", "skipped_count", "sample_size_bytes"])

    for year in range(2014, 2024):
        csv_path = download_root / f"quakes_{year}.csv"
        if not csv_path.is_file():
            raise SystemExit(f"missing raw CSV: {csv_path}")
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise SystemExit(f"empty raw CSV: {csv_path}")

        for series in series_defs:
            values = []
            skipped_count = 0
            for row in rows:
                raw = (row.get(series["column"]) or "").strip()
                if raw == "":
                    skipped_count += 1
                    continue
                if series["array_type"] == "H":
                    try:
                        value = int(raw)
                    except ValueError:
                        skipped_count += 1
                        continue
                    if value < 0 or value > 65535:
                        skipped_count += 1
                        continue
                    values.append(value)
                else:
                    try:
                        value = float(raw)
                    except ValueError:
                        skipped_count += 1
                        continue
                    values.append(value)

            payload = array.array(series["array_type"], values)
            if payload.itemsize > 1 and os.sys.byteorder != "little":
                payload.byteswap()

            out_path = samples_root / series["series_id"] / f"{year}.bin"
            with out_path.open("wb") as out_file:
                out_file.write(payload.tobytes())
            sample_size_bytes = out_path.stat().st_size

            writer.writerow([year, series["series_id"], len(rows), len(values), skipped_count, sample_size_bytes])
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
                    "value_count": len(values),
                }
            )

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
PY

say "built samples under ${SAMPLES_ROOT}"
