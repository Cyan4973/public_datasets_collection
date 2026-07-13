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
import os
from pathlib import Path

download_root = Path(os.environ["DOWNLOAD_ROOT"])
filtered_root = Path(os.environ["FILTERED_ROOT"])
index_root = Path(os.environ["INDEX_ROOT"])
samples_root = Path(os.environ["SAMPLES_ROOT"])
data_root = samples_root.parent.parent

stats_path = filtered_root / "year_series_stats.tsv"
index_path = index_root / "samples.jsonl"
failures_path = download_root / "download_failures.tsv"

series_defs = [
    {"series_id": "eq_depth_f64", "column": "depth", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "eq_mag_f64", "column": "mag", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "eq_gap_f64", "column": "gap", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "eq_dmin_f64", "column": "dmin", "numeric_kind": "float", "bit_width": 64, "endianness": "little", "element_size_bytes": 8},
    {"series_id": "eq_nst_u16", "column": "nst", "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2},
]

if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

with stats_path.open("r", encoding="utf-8", newline="") as handle:
    stats_rows = list(csv.DictReader(handle, delimiter="\t"))
stats_by_key = {(row["year"], row["series_id"]): row for row in stats_rows}

expected_records: dict[tuple[str, str], dict[str, object]] = {}

for year in range(2014, 2024):
    csv_path = download_root / f"quakes_{year}.csv"
    if not csv_path.is_file():
        raise SystemExit(f"missing raw CSV: {csv_path}")
    if csv_path.stat().st_size <= 0:
        raise SystemExit(f"empty raw CSV: {csv_path}")
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"empty parsed CSV: {csv_path}")

    for series in series_defs:
        value_count = 0
        skipped_count = 0
        for row in rows:
            raw = (row.get(series["column"]) or "").strip()
            if raw == "":
                skipped_count += 1
                continue
            if series["numeric_kind"] == "uint":
                try:
                    value = int(raw)
                except ValueError:
                    skipped_count += 1
                    continue
                if value < 0 or value > 65535:
                    skipped_count += 1
                    continue
            else:
                try:
                    float(raw)
                except ValueError:
                    skipped_count += 1
                    continue
            value_count += 1

        sample_path = samples_root / series["series_id"] / f"{year}.bin"
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        sample_size_bytes = sample_path.stat().st_size
        expected_size = value_count * int(series["element_size_bytes"])
        if sample_size_bytes != expected_size:
            raise SystemExit(
                f"wrong size for {sample_path}: expected {expected_size}, got {sample_size_bytes}"
            )

        stats_row = stats_by_key.get((str(year), series["series_id"]))
        if stats_row is None:
            raise SystemExit(f"missing stats row for {year} {series['series_id']}")
        if int(stats_row["row_count"]) != len(rows):
            raise SystemExit(
                f"row count mismatch for {year} {series['series_id']}: stats={stats_row['row_count']} raw={len(rows)}"
            )
        if int(stats_row["value_count"]) != value_count:
            raise SystemExit(
                f"value count mismatch for {year} {series['series_id']}: stats={stats_row['value_count']} raw={value_count}"
            )
        if int(stats_row["skipped_count"]) != skipped_count:
            raise SystemExit(
                f"skipped count mismatch for {year} {series['series_id']}: stats={stats_row['skipped_count']} raw={skipped_count}"
            )
        if int(stats_row["sample_size_bytes"]) != sample_size_bytes:
            raise SystemExit(
                f"sample size mismatch for {year} {series['series_id']}: stats={stats_row['sample_size_bytes']} actual={sample_size_bytes}"
            )

        expected_records[(series["series_id"], str(year))] = {
            "dataset_id": "earthquake_usgs",
            "series_id": series["series_id"],
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": series["numeric_kind"],
            "bit_width": series["bit_width"],
            "endianness": series["endianness"],
            "element_size_bytes": series["element_size_bytes"],
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
        year = Path(sample_path).stem if isinstance(sample_path, str) else ""
        key = (record.get("series_id"), year)
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

print("verified raw inventory, generated sample sizes, stats, and sample index")
PY

say "verified raw inventory, generated sample sizes, stats, and sample index"
