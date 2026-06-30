#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_water_sites_rdb"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export USGS_WATER_SITES_MIN_RETAINED_RECORDS="${USGS_WATER_SITES_MIN_RETAINED_RECORDS:-20000}"
export USGS_WATER_SITES_MIN_PRIMARY_VALUES="${USGS_WATER_SITES_MIN_PRIMARY_VALUES:-100000}"
export USGS_WATER_SITES_MIN_PRIMARY_BYTES="${USGS_WATER_SITES_MIN_PRIMARY_BYTES:-102400}"
export USGS_WATER_SITES_MIN_MEDIAN_VALUES="${USGS_WATER_SITES_MIN_MEDIAN_VALUES:-1000}"
python3 - <<'PY' "$REPO_ROOT" "$DATA_DIR" "$FILTER_DIR" "$INDEX_DIR"
from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
data_dir = sys.argv[2]
filter_dir = Path(sys.argv[3])
index_dir = Path(sys.argv[4])
min_retained = int(os.environ["USGS_WATER_SITES_MIN_RETAINED_RECORDS"])
min_primary_values = int(os.environ["USGS_WATER_SITES_MIN_PRIMARY_VALUES"])
min_primary_bytes = int(os.environ["USGS_WATER_SITES_MIN_PRIMARY_BYTES"])
min_median_values = int(os.environ["USGS_WATER_SITES_MIN_MEDIAN_VALUES"])

stats = json.load((filter_dir / "ingest_stats.json").open(encoding="utf-8"))
rows = [json.loads(line) for line in (index_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
expected_series = {
    "usgs_site_no",
    "usgs_dec_lat",
    "usgs_dec_long",
    "usgs_altitude",
    "usgs_alt_accuracy",
    "usgs_huc_cd",
}
expected_roles = {
    "usgs_site_no": "auxiliary",
    "usgs_dec_lat": "primary",
    "usgs_dec_long": "primary",
    "usgs_altitude": "primary",
    "usgs_alt_accuracy": "primary",
    "usgs_huc_cd": "primary",
}
series_ids = {row["series_id"] for row in rows}
if series_ids != expected_series:
    raise SystemExit(f"series mismatch: {sorted(series_ids)}")

retained = int(stats["retained_records"])
if retained < min_retained:
    raise SystemExit(f"retained_records below repair floor: {retained} < {min_retained}")
if int(stats["primary_values"]) < min_primary_values:
    raise SystemExit(f"primary_values below repair target: {stats['primary_values']} < {min_primary_values}")
if int(stats["primary_sample_bytes"]) < min_primary_bytes:
    raise SystemExit(f"primary_sample_bytes below floor: {stats['primary_sample_bytes']} < {min_primary_bytes}")

value_counts = []
sample_bytes = []
primary_value_counts = []
primary_sample_bytes = []
for row in rows:
    role = row.get("role")
    if role != expected_roles[row["series_id"]]:
        raise SystemExit(f"{row['series_id']}: expected role {expected_roles[row['series_id']]} got {role}")
    if int(row["value_count"]) != retained:
        raise SystemExit(f"{row['series_id']}: value_count {row['value_count']} != retained_records {retained}")
    if row.get("min") == row.get("max"):
        raise SystemExit(f"{row['series_id']}: constant min/max")
    sample = repo_root / data_dir / row["sample_path"]
    if not sample.exists():
        raise SystemExit(f"missing sample: {sample}")
    expected_size = int(row["value_count"]) * int(row["element_size_bytes"])
    actual_size = sample.stat().st_size
    if actual_size != expected_size or actual_size != int(row["sample_size_bytes"]):
        raise SystemExit(f"{row['series_id']}: sample size mismatch")
    value_counts.append(int(row["value_count"]))
    sample_bytes.append(actual_size)
    if role == "primary":
        primary_value_counts.append(int(row["value_count"]))
        primary_sample_bytes.append(actual_size)

if statistics.median(primary_value_counts) < min_median_values:
    raise SystemExit("median value count below floor")
if sum(primary_value_counts) != int(stats["primary_values"]):
    raise SystemExit("primary_values statistic mismatch")
if sum(primary_sample_bytes) != int(stats["primary_sample_bytes"]):
    raise SystemExit("primary_sample_bytes statistic mismatch")

print(
    f"verified_samples={len(rows)} retained_records={retained} "
    f"primary_values={sum(primary_value_counts)} primary_sample_bytes={sum(primary_sample_bytes)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
