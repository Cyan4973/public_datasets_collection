#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nomis_employment"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export NOMIS_MIN_RETAINED_RECORDS="${NOMIS_MIN_RETAINED_RECORDS:-10000}"
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "nomis_employment"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_retained = int(os.environ["NOMIS_MIN_RETAINED_RECORDS"])


def as_uint(value: object, field: str, max_value: int) -> int:
    parsed = int(value)
    if parsed < 0 or parsed > max_value:
        raise ValueError(f"{field} out of range [0, {max_value}]: {parsed}")
    return parsed


def parse_time(value: object) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError("time value is not a string")
    year_s, month_s = value.split("-", 1)
    year = as_uint(year_s, "year", 0xFFFF)
    month = as_uint(month_s, "month", 0xFF)
    if month < 1 or month > 12:
        raise ValueError(f"month out of range: {month}")
    return year, month


source_path = download_dir / "nomis_employment.json"
if not source_path.is_file():
    raise SystemExit(f"missing local NOMIS payload: {source_path}; run download.sh first")
src = json.loads(source_path.read_text(encoding="utf-8"))
source_rows = src.get("obs")
if not isinstance(source_rows, list):
    raise SystemExit("missing obs list in NOMIS payload")

index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

series_meta = {
    "nomis_obs_value": ("uint", 32, 4, "I", "Persons claiming JSA."),
    "nomis_geography": ("uint", 32, 4, "I", "NOMIS geography dimension code."),
    "nomis_sex": ("uint", 8, 1, "B", "NOMIS sex dimension code."),
    "nomis_year": ("uint", 16, 2, "H", "Observation calendar year."),
    "nomis_month": ("uint", 8, 1, "B", "Observation calendar month."),
}
values: dict[str, list[int]] = {series_id: [] for series_id in series_meta}
skipped = 0

for row in source_rows:
    try:
        obs_value = as_uint(row["obs_value"]["value"], "obs_value", 0xFFFFFFFF)
        geography = as_uint(row["geography"]["value"], "geography", 0xFFFFFFFF)
        sex = as_uint(row["sex"]["value"], "sex", 0xFF)
        year, month = parse_time(row["time"]["value"])
    except Exception:
        skipped += 1
        continue
    values["nomis_obs_value"].append(obs_value)
    values["nomis_geography"].append(geography)
    values["nomis_sex"].append(sex)
    values["nomis_year"].append(year)
    values["nomis_month"].append(month)

retained = len(values["nomis_obs_value"])
if retained < min_retained:
    raise SystemExit(f"only {retained} retained rows < NOMIS_MIN_RETAINED_RECORDS={min_retained}; rerun download.sh")

lengths = {len(series_values) for series_values in values.values()}
if lengths != {retained}:
    raise SystemExit(f"series length mismatch: {sorted(lengths)}")

counts = [len(series_values) for series_values in values.values()]
byte_counts = [
    len(values[series_id]) * element_size
    for series_id, (_kind, _bits, element_size, _code, _description) in series_meta.items()
]
if sum(counts) < 10_000 and sum(byte_counts) < 102_400:
    raise SystemExit(f"below aggregate floor: values={sum(counts)} bytes={sum(byte_counts)}")
if statistics.median(counts) < 1_000:
    raise SystemExit(f"median sample values below floor: {statistics.median(counts)}")
for series_id, series_values in values.items():
    if min(series_values) == max(series_values):
        raise SystemExit(f"constant sample after filtering: {series_id}")

for child in samples_dir.glob("*"):
    if child.is_dir():
        shutil.rmtree(child)

rows = []
for series_id, (kind, bits, element_size, code, description) in series_meta.items():
    series_values = values[series_id]
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_n{len(series_values):06d}.bin"
    with out.open("wb") as fh:
        for offset in range(0, len(series_values), 8192):
            chunk = series_values[offset : offset + 8192]
            fh.write(struct.pack("<" + code * len(chunk), *chunk))
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": element_size,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(series_values),
            "sample_format": f"raw homogeneous {kind}{bits} array",
            "sample_geometry": "nomis_employment_observation_column",
            "sample_rank": 1,
            "sample_shape": [len(series_values)],
            "sample_axes": ["nomis_observation"],
            "natural_record_kind": "nomis_observation",
            "natural_record_count": retained,
            "natural_record_values": 1,
            "field_description": description,
            "min": min(series_values),
            "max": max(series_values),
        }
    )

counts = [int(row["value_count"]) for row in rows]
byte_counts = [int(row["sample_size_bytes"]) for row in rows]
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "source_records": len(source_rows),
            "retained_records": retained,
            "skipped_records": skipped,
            "primary_values": sum(counts),
            "primary_sample_bytes": sum(byte_counts),
            "median_primary_values": statistics.median(counts),
            "series": {
                row["series_id"]: {
                    "sample_count": 1,
                    "total_values": int(row["value_count"]),
                    "total_size_bytes": int(row["sample_size_bytes"]),
                    "min": int(row["min"]),
                    "max": int(row["max"]),
                }
                for row in rows
            },
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built samples={len(rows)} retained_records={retained} "
    f"values={sum(counts)} bytes={sum(byte_counts)} skipped={skipped}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
