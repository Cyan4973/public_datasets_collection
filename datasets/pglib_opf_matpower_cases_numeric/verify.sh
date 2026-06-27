#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="pglib_opf_matpower_cases_numeric"
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
EXPECTED_SERIES = {
    "bus_matrix_f64",
    "branch_matrix_f64",
    "gen_matrix_f64",
    "gencost_matrix_f64",
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
unknown = series_seen - EXPECTED_SERIES
if unknown:
    raise SystemExit(f"unexpected series: {sorted(unknown)}")
if not {"bus_matrix_f64", "branch_matrix_f64"} <= series_seen:
    raise SystemExit(f"missing core graph matrix families: {sorted(series_seen)}")

counts = [int(row["value_count"]) for row in primary]
bytes_by_row = [int(row["sample_size_bytes"]) for row in primary]
total_values = sum(counts)
total_bytes = sum(bytes_by_row)
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
    if row.get("dataset_id") != DATASET_ID:
        raise SystemExit(f"wrong dataset_id in row: {row}")
    series_id = str(row["series_id"])
    series_counts[series_id] = series_counts.get(series_id, 0) + 1
    if row["sample_path"] in seen_paths:
        raise SystemExit(f"duplicate sample path: {row['sample_path']}")
    seen_paths.add(row["sample_path"])
    if row["numeric_kind"] != "float" or int(row["bit_width"]) != 64:
        raise SystemExit(f"not float64: {row['sample_path']}")
    if row["endianness"] != "little" or int(row["element_size_bytes"]) != 8:
        raise SystemExit(f"bad element encoding: {row['sample_path']}")
    if row.get("sample_geometry") != "matpower_case_matrix" or int(row.get("sample_rank", 0)) != 2:
        raise SystemExit(f"unexpected geometry: {row['sample_path']}")
    shape = row.get("sample_shape")
    if not isinstance(shape, list) or len(shape) != 2:
        raise SystemExit(f"bad sample shape: {row['sample_path']}")
    row_count, column_count = int(shape[0]), int(shape[1])
    if row_count <= 0 or column_count <= 0:
        raise SystemExit(f"nonpositive matrix shape: {row['sample_path']}")
    if row_count * column_count != int(row["value_count"]):
        raise SystemExit(f"shape/value mismatch: {row['sample_path']}")
    sample_path = DATA_ROOT / row["sample_path"]
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {row['sample_path']}")
    data = sample_path.read_bytes()
    if len(data) != int(row["sample_size_bytes"]) or len(data) != int(row["value_count"]) * 8:
        raise SystemExit(f"sample size mismatch: {row['sample_path']}")
    min_value = math.inf
    max_value = -math.inf
    checked = 0
    for (value,) in struct.iter_unpack("<d", data):
        if not math.isfinite(value):
            raise SystemExit(f"non-finite value in {row['sample_path']}")
        min_value = min(min_value, value)
        max_value = max(max_value, value)
        checked += 1
    if checked != int(row["value_count"]):
        raise SystemExit(f"value count mismatch after unpack: {row['sample_path']}")
    if not min_value < max_value:
        raise SystemExit(f"constant sample: {row['sample_path']}")
    if abs(float(row["min"]) - min_value) > 1e-9 or abs(float(row["max"]) - max_value) > 1e-9:
        raise SystemExit(f"index min/max mismatch: {row['sample_path']}")

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
