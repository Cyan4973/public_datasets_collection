#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
DATA_DIR=${DATA_DIR:-"${REPO_ROOT}/.data"}
DATASET_ID="fred_treasury_yields_daily_bundle"
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

DOWNLOAD_ROOT="${DOWNLOAD_ROOT}" FILTERED_ROOT="${FILTERED_ROOT}" INDEX_ROOT="${INDEX_ROOT}" SAMPLES_ROOT="${SAMPLES_ROOT}" python3 - <<'PY' >>"${LOG_FILE}" 2>&1
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

dataset_id = "fred_treasury_yields_daily_bundle"
series_id = "treasury_yield_percent_f32"
sample_format = "raw homogeneous float32 Treasury yield percent array"
natural_record_kind = "fred_treasury_constant_maturity_series"
min_series = int(os.environ.get("FRED_TREASURY_MIN_SERIES", "8"))
min_sample_values = int(os.environ.get("FRED_TREASURY_MIN_SAMPLE_VALUES", "1000"))
min_total_values = int(os.environ.get("FRED_TREASURY_MIN_TOTAL_VALUES", "100000"))
planned = [
    ("DGS1MO", "1mo", "treasury_1mo.csv"),
    ("DGS3MO", "3mo", "treasury_3mo.csv"),
    ("DGS6MO", "6mo", "treasury_6mo.csv"),
    ("DGS1", "1y", "treasury_1y.csv"),
    ("DGS2", "2y", "treasury_2y.csv"),
    ("DGS3", "3y", "treasury_3y.csv"),
    ("DGS5", "5y", "treasury_5y.csv"),
    ("DGS7", "7y", "treasury_7y.csv"),
    ("DGS10", "10y", "treasury_10y.csv"),
    ("DGS20", "20y", "treasury_20y.csv"),
    ("DGS30", "30y", "treasury_30y.csv"),
]

series_dir = samples_root / series_id
if series_dir.exists():
    shutil.rmtree(series_dir)
series_dir.mkdir(parents=True, exist_ok=True)
filtered_root.mkdir(parents=True, exist_ok=True)
index_root.mkdir(parents=True, exist_ok=True)

stats_path = filtered_root / "series_stats.tsv"
index_path = index_root / "samples.jsonl"
index_records = []
accepted = []
missing = []

with stats_path.open("w", encoding="utf-8", newline="") as stats_file:
    writer = csv.writer(stats_file, delimiter="\t")
    writer.writerow([
        "fred_series_id",
        "maturity",
        "source_file",
        "row_count",
        "kept_count",
        "skipped_blank_count",
        "skipped_parse_count",
        "start_date",
        "end_date",
        "min",
        "max",
    ])
    for fred_series_id, maturity, rel_name in planned:
        path = download_root / rel_name
        if not path.is_file():
            missing.append(rel_name)
            continue
        row_count = 0
        skipped_blank_count = 0
        skipped_parse_count = 0
        parsed = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["observation_date", fred_series_id]:
                raise SystemExit(f"unexpected CSV header in {path}: {reader.fieldnames!r}")
            for row in reader:
                row_count += 1
                raw_date = str(row.get("observation_date", "")).strip()
                raw_value = str(row.get(fred_series_id, "")).strip()
                if raw_date == "" or raw_value in {"", "."}:
                    skipped_blank_count += 1
                    continue
                try:
                    year_s, month_s, day_s = raw_date.split("-")
                    year = int(year_s)
                    month = int(month_s)
                    day = int(day_s)
                    value = float(raw_value)
                except (TypeError, ValueError):
                    skipped_parse_count += 1
                    continue
                if year < 1900 or year > 2100 or month < 1 or month > 12 or day < 1 or day > 31 or not math.isfinite(value):
                    skipped_parse_count += 1
                    continue
                parsed.append((raw_date, value))
        parsed.sort()
        values = [value for _, value in parsed]
        kept_count = len(values)
        if kept_count < min_sample_values:
            writer.writerow([
                fred_series_id,
                maturity,
                rel_name,
                row_count,
                kept_count,
                skipped_blank_count,
                skipped_parse_count,
                parsed[0][0] if parsed else "",
                parsed[-1][0] if parsed else "",
                min(values) if values else "",
                max(values) if values else "",
            ])
            continue
        payload = array.array("f", values)
        if payload.itemsize > 1 and os.sys.byteorder != "little":
            payload.byteswap()
        out_path = series_dir / f"{fred_series_id.lower()}.bin"
        with out_path.open("wb") as out_file:
            out_file.write(payload.tobytes())
        sample_size_bytes = out_path.stat().st_size
        record = {
            "dataset_id": dataset_id,
            "series_id": series_id,
            "sample_path": out_path.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": sample_size_bytes,
            "value_count": kept_count,
            "sample_format": sample_format,
            "sample_geometry": "time_series",
            "sample_rank": 1,
            "sample_axes": ["observation_day"],
            "natural_record_kind": natural_record_kind,
            "fred_series_id": fred_series_id,
            "maturity": maturity,
            "source_file": rel_name,
            "start_date": parsed[0][0],
            "end_date": parsed[-1][0],
            "min": min(values),
            "max": max(values),
        }
        index_records.append(record)
        accepted.append(record)
        writer.writerow([
            fred_series_id,
            maturity,
            rel_name,
            row_count,
            kept_count,
            skipped_blank_count,
            skipped_parse_count,
            parsed[0][0],
            parsed[-1][0],
            min(values),
            max(values),
        ])

total_values = sum(int(record["value_count"]) for record in accepted)
total_bytes = sum(int(record["sample_size_bytes"]) for record in accepted)
if len(accepted) < min_series:
    raise SystemExit(f"insufficient accepted maturity series: {len(accepted)} < {min_series}; missing={missing}")
if total_values < min_total_values:
    raise SystemExit(f"insufficient total values: {total_values} < {min_total_values}")

with index_path.open("w", encoding="utf-8", newline="") as index_file:
    for record in index_records:
        index_file.write(json.dumps(record, sort_keys=True))
        index_file.write("\n")
print(f"built_samples={len(accepted)} primary_values={total_values} primary_bytes={total_bytes}")
PY

say "built samples under ${SAMPLES_ROOT}"
