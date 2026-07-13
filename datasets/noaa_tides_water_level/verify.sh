#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=noaa_tides_water_level
INDEX_PATH="$DATA_DIR/index/$DATASET_ID/samples.jsonl"
FILTERED_PATH="$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

MIN_VALUES_PER_SAMPLE="${NOAA_TIDES_VERIFY_MIN_VALUES_PER_SAMPLE:-100000}"
MIN_SAMPLES_PER_SERIES="${NOAA_TIDES_VERIFY_MIN_SAMPLES_PER_SERIES:-15}"
MIN_VALUES_PER_SERIES="${NOAA_TIDES_VERIFY_MIN_VALUES_PER_SERIES:-1500000}"

python3 - <<'PY' "$INDEX_PATH" "$FILTERED_PATH" "$DATA_DIR" "$MIN_VALUES_PER_SAMPLE" "$MIN_SAMPLES_PER_SERIES" "$MIN_VALUES_PER_SERIES"
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

idx_path, stats_path, data_dir, min_values, min_samples, min_series_values = sys.argv[1:7]
min_values = int(min_values)
min_samples = int(min_samples)
min_series_values = int(min_series_values)
data_root = Path(data_dir)
rows = [json.loads(line) for line in open(idx_path, encoding="utf-8") if line.strip()]
stats = json.load(open(stats_path, encoding="utf-8"))
expected_series = {"noaa_tides_level_f64", "noaa_tides_sigma_f64"}
series_ids = {row["series_id"] for row in rows}
if series_ids != expected_series:
    raise SystemExit(f"unexpected series set: {sorted(series_ids)}")

series_counts = {series_id: 0 for series_id in expected_series}
series_values = {series_id: 0 for series_id in expected_series}
seen_paths = set()
for row in rows:
    sample_path = data_root / row["sample_path"]
    if sample_path in seen_paths:
        raise SystemExit(f"duplicate sample path: {sample_path}")
    seen_paths.add(sample_path)
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    actual_size = os.path.getsize(sample_path)
    if actual_size != int(row["sample_size_bytes"]):
        raise SystemExit(f"size mismatch for {sample_path}: {actual_size} != {row['sample_size_bytes']}")
    value_count = int(row["value_count"])
    if value_count < min_values:
        raise SystemExit(f"sample below minimum values: {sample_path} has {value_count}")
    expected_size = value_count * int(row["element_size_bytes"])
    if actual_size != expected_size:
        raise SystemExit(f"value_count/size mismatch for {sample_path}: {expected_size} != {actual_size}")
    series_counts[row["series_id"]] += 1
    series_values[row["series_id"]] += value_count

for series_id in expected_series:
    if series_counts[series_id] < min_samples:
        raise SystemExit(f"{series_id} has only {series_counts[series_id]} samples, minimum is {min_samples}")
    if series_values[series_id] < min_series_values:
        raise SystemExit(f"{series_id} has only {series_values[series_id]} values, minimum is {min_series_values}")

if int(stats["primary_values"]) != sum(series_values.values()):
    raise SystemExit("stats primary_values mismatch")
if int(stats["sample_count"]) != len(rows):
    raise SystemExit("stats sample_count mismatch")
print(
    f"verified_samples={len(rows)} series_counts={series_counts} "
    f"series_values={series_values} rows_skipped={stats['rows_skipped']}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
