#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="hsl_gtfs_static_schedule_numeric"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR DATASET_ID FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
import statistics
import struct
from pathlib import Path

DATASET_ID = os.environ["DATASET_ID"]
DATA_ROOT = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
INDEX_PATH = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
STATS_PATH = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
EXPECTED = {
    "stop_times_arrival_seconds_i32": ("int", 32, 4, "<i", 1),
    "stop_times_departure_seconds_i32": ("int", 32, 4, "<i", 1),
    "stop_times_stop_sequence_u32": ("uint", 32, 4, "<I", 1),
    "stop_times_shape_dist_traveled_f64": ("float", 64, 8, "<d", 1),
    "shapes_lat_lon_f64": ("float", 64, 8, "<d", 2),
    "shapes_sequence_u32": ("uint", 32, 4, "<I", 1),
    "shapes_dist_traveled_f64": ("float", 64, 8, "<d", 1),
    "stops_lat_lon_f64": ("float", 64, 8, "<d", 2),
    "frequencies_start_end_headway_seconds_i32": ("int", 32, 4, "<i", 2),
}
REQUIRED = {
    "stop_times_arrival_seconds_i32",
    "stop_times_departure_seconds_i32",
    "stop_times_stop_sequence_u32",
    "shapes_lat_lon_f64",
    "shapes_sequence_u32",
    "stops_lat_lon_f64",
}
MIN_SAMPLES = 2
MIN_MEDIAN_VALUES = 1_000
MIN_TOTAL_VALUES = 10_000
MIN_TOTAL_BYTES = 102_400
MAX_PRIMARY_BYTES = 1_000_000_000

if not INDEX_PATH.is_file():
    raise SystemExit(f"missing sample index: {INDEX_PATH}")
if not STATS_PATH.is_file():
    raise SystemExit(f"missing ingest stats: {STATS_PATH}")

rows = [json.loads(line) for line in INDEX_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
primary = [row for row in rows if row.get("role", "primary") == "primary"]
if len(primary) < MIN_SAMPLES:
    raise SystemExit(f"only {len(primary)} primary samples < {MIN_SAMPLES}")

series_seen = {str(row["series_id"]) for row in primary}
unknown = series_seen - set(EXPECTED)
if unknown:
    raise SystemExit(f"unexpected series: {sorted(unknown)}")
missing = REQUIRED - series_seen
if missing:
    raise SystemExit(f"missing required series: {sorted(missing)}")

counts = [int(row["value_count"]) for row in primary]
byte_counts = [int(row["sample_size_bytes"]) for row in primary]
total_values = sum(counts)
total_bytes = sum(byte_counts)
median_values = statistics.median(counts)
if total_values < MIN_TOTAL_VALUES and total_bytes < MIN_TOTAL_BYTES:
    raise SystemExit(f"below aggregate floor: values={total_values} bytes={total_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")

seen_paths: set[str] = set()
series_counts: dict[str, int] = {}
for row in primary:
    series_id = str(row["series_id"])
    expected_kind, expected_width, expected_element_size, fmt, expected_rank = EXPECTED[series_id]
    series_counts[series_id] = series_counts.get(series_id, 0) + 1
    if row.get("dataset_id") != DATASET_ID:
        raise SystemExit(f"wrong dataset_id in {row['sample_path']}")
    if row["sample_path"] in seen_paths:
        raise SystemExit(f"duplicate sample path: {row['sample_path']}")
    seen_paths.add(row["sample_path"])
    if row["numeric_kind"] != expected_kind or int(row["bit_width"]) != expected_width:
        raise SystemExit(f"encoding mismatch: {row['sample_path']}")
    if row["endianness"] != "little" or int(row["element_size_bytes"]) != expected_element_size:
        raise SystemExit(f"element mismatch: {row['sample_path']}")
    if int(row.get("sample_rank", 0)) != expected_rank:
        raise SystemExit(f"rank mismatch: {row['sample_path']}")
    shape = row.get("sample_shape")
    if not isinstance(shape, list) or len(shape) != expected_rank:
        raise SystemExit(f"shape rank mismatch: {row['sample_path']}")
    if any(int(dim) <= 0 for dim in shape):
        raise SystemExit(f"nonpositive shape: {row['sample_path']}")
    product = 1
    for dim in shape:
        product *= int(dim)
    if product != int(row["value_count"]):
        raise SystemExit(f"shape/value mismatch: {row['sample_path']}")

    sample_path = DATA_ROOT / row["sample_path"]
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {row['sample_path']}")
    data = sample_path.read_bytes()
    if len(data) != int(row["sample_size_bytes"]) or len(data) != int(row["value_count"]) * expected_element_size:
        raise SystemExit(f"sample size mismatch: {row['sample_path']}")

    min_value: int | float | None = None
    max_value: int | float | None = None
    checked = 0
    for (value,) in struct.iter_unpack(fmt, data):
        if isinstance(value, float) and not math.isfinite(value):
            raise SystemExit(f"non-finite value in {row['sample_path']}")
        min_value = value if min_value is None else min(min_value, value)
        max_value = value if max_value is None else max(max_value, value)
        checked += 1
    if checked != int(row["value_count"]):
        raise SystemExit(f"value count unpack mismatch: {row['sample_path']}")
    if min_value is None or max_value is None or not min_value < max_value:
        raise SystemExit(f"constant sample: {row['sample_path']}")
    if abs(float(row["min"]) - float(min_value)) > 1e-9 or abs(float(row["max"]) - float(max_value)) > 1e-9:
        raise SystemExit(f"index min/max mismatch: {row['sample_path']}")

    if series_id.endswith("_seconds_i32") or series_id == "frequencies_start_end_headway_seconds_i32":
        if min_value < 0:
            raise SystemExit(f"negative seconds/headway in {row['sample_path']}")
    if series_id == "shapes_lat_lon_f64" or series_id == "stops_lat_lon_f64":
        values = [value for (value,) in struct.iter_unpack(fmt, data)]
        lats = values[0::2]
        lons = values[1::2]
        if not all(-90 <= value <= 90 for value in lats):
            raise SystemExit(f"latitude out of range in {row['sample_path']}")
        if not all(-180 <= value <= 180 for value in lons):
            raise SystemExit(f"longitude out of range in {row['sample_path']}")

stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
if int(stats["primary_sample_count"]) != len(primary):
    raise SystemExit("stats primary_sample_count mismatch")
if int(stats["primary_values"]) != total_values:
    raise SystemExit("stats primary_values mismatch")
if int(stats["primary_sample_bytes"]) != total_bytes:
    raise SystemExit("stats primary_sample_bytes mismatch")
if int(stats["median_primary_values"]) != int(median_values):
    raise SystemExit("stats median_primary_values mismatch")

print(
    f"verified samples={len(primary)} median_values={int(median_values)} "
    f"total_values={total_values} total_bytes={total_bytes} series={series_counts}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
