#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eurostat_unemployment_monthly"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_VALUES="${EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_VALUES:-100000}"
export EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_BYTES="${EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_BYTES:-400000}"
export EUROSTAT_UNEMPLOYMENT_MIN_MEDIAN_VALUES="${EUROSTAT_UNEMPLOYMENT_MIN_MEDIAN_VALUES:-100000}"
python3 - <<'PY' "$REPO_ROOT" "$DATA_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR"
from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
data_dir = sys.argv[2]
download_dir = Path(sys.argv[3])
filter_dir = Path(sys.argv[4])
index_dir = Path(sys.argv[5])
min_primary_values = int(os.environ["EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_VALUES"])
min_primary_bytes = int(os.environ["EUROSTAT_UNEMPLOYMENT_MIN_PRIMARY_BYTES"])
min_median_values = int(os.environ["EUROSTAT_UNEMPLOYMENT_MIN_MEDIAN_VALUES"])

failures_path = download_dir / "download_failures.tsv"
if failures_path.is_file() and failures_path.stat().st_size > 0:
    raise SystemExit(f"download failures recorded in {failures_path}")
if not (download_dir / "data.json").is_file():
    raise SystemExit("missing downloaded data.json")

stats = json.loads((filter_dir / "ingest_stats.json").read_text(encoding="utf-8"))
rows = [json.loads(line) for line in (index_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
expected_roles = {
    "unemployment_rate_f32": "primary",
    "eurostat_unemployment_s_adj_index": "auxiliary",
    "eurostat_unemployment_age_index": "auxiliary",
    "eurostat_unemployment_sex_index": "auxiliary",
    "eurostat_unemployment_geo_index": "auxiliary",
    "eurostat_unemployment_month_ordinal": "auxiliary",
}
series_ids = {row["series_id"] for row in rows}
if series_ids != set(expected_roles):
    raise SystemExit(f"series mismatch: {sorted(series_ids)}")

primary_counts = []
primary_bytes = []
for row in rows:
    series_id = row["series_id"]
    role = row.get("role")
    if role != expected_roles[series_id]:
        raise SystemExit(f"{series_id}: expected role {expected_roles[series_id]} got {role}")
    sample = repo_root / data_dir / row["sample_path"]
    if not sample.is_file():
        raise SystemExit(f"missing sample {row['sample_path']}")
    expected_size = int(row["value_count"]) * int(row["element_size_bytes"])
    actual_size = sample.stat().st_size
    if actual_size != expected_size or actual_size != int(row["sample_size_bytes"]):
        raise SystemExit(f"{series_id}: sample size mismatch")
    if int(row["value_count"]) != int(stats["retained_records"]):
        raise SystemExit(f"{series_id}: value_count does not match retained_records")
    if role == "primary":
        if row.get("min") == row.get("max"):
            raise SystemExit(f"{series_id}: constant min/max")
        primary_counts.append(int(row["value_count"]))
        primary_bytes.append(actual_size)

if sum(primary_counts) != int(stats["primary_values"]):
    raise SystemExit("primary_values statistic mismatch")
if sum(primary_bytes) != int(stats["primary_sample_bytes"]):
    raise SystemExit("primary_sample_bytes statistic mismatch")
if sum(primary_counts) < min_primary_values:
    raise SystemExit(f"primary values below floor: {sum(primary_counts)} < {min_primary_values}")
if sum(primary_bytes) < min_primary_bytes:
    raise SystemExit(f"primary bytes below floor: {sum(primary_bytes)} < {min_primary_bytes}")
if statistics.median(primary_counts) < min_median_values:
    raise SystemExit(f"median primary values below floor: {statistics.median(primary_counts)}")

print(
    f"verified_samples={len(rows)} primary_values={sum(primary_counts)} "
    f"primary_sample_bytes={sum(primary_bytes)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
