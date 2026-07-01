#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eia_series_petroleum"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export EIA_PETROLEUM_MIN_PRIMARY_BYTES="${EIA_PETROLEUM_MIN_PRIMARY_BYTES:-102400}"
export EIA_PETROLEUM_MIN_MEDIAN_VALUES="${EIA_PETROLEUM_MIN_MEDIAN_VALUES:-1000}"
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
min_primary_bytes = int(os.environ["EIA_PETROLEUM_MIN_PRIMARY_BYTES"])
min_median_values = int(os.environ["EIA_PETROLEUM_MIN_MEDIAN_VALUES"])

stats = json.loads((filter_dir / "ingest_stats.json").read_text(encoding="utf-8"))
rows = [json.loads(line) for line in (index_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
if not rows:
    raise SystemExit("missing sample index rows")

primary_rows = []
aux_rows = []
for row in rows:
    role = row.get("role")
    if role == "primary":
        if not str(row["series_id"]).startswith("eia_petroleum_spot_price_"):
            raise SystemExit(f"unexpected primary series_id: {row['series_id']}")
        if row["numeric_kind"] != "float" or int(row["bit_width"]) != 64:
            raise SystemExit(f"unexpected primary numeric type: {row['series_id']}")
        primary_rows.append(row)
    elif role == "auxiliary":
        if row["series_id"] != "eia_petroleum_period_ordinal":
            raise SystemExit(f"unexpected auxiliary series_id: {row['series_id']}")
        aux_rows.append(row)
    else:
        raise SystemExit(f"unexpected role for {row['series_id']}: {role}")

if len(primary_rows) == 0:
    raise SystemExit("missing primary rows")
if len(aux_rows) != len(primary_rows):
    raise SystemExit(f"expected one auxiliary date axis per primary sample, got primary={len(primary_rows)} aux={len(aux_rows)}")

primary_counts = []
primary_bytes = []
for row in rows:
    sample = repo_root / data_dir / row["sample_path"]
    if not sample.is_file():
        raise SystemExit(f"missing sample {row['sample_path']}")
    expected_size = int(row["value_count"]) * int(row["element_size_bytes"])
    actual_size = sample.stat().st_size
    if actual_size != expected_size or actual_size != int(row["sample_size_bytes"]):
        raise SystemExit(f"sample size mismatch {row['sample_path']}")
    if row.get("min") == row.get("max"):
        raise SystemExit(f"constant min/max {row['sample_path']}")
    if row["role"] == "primary":
        primary_counts.append(int(row["value_count"]))
        primary_bytes.append(actual_size)

if sum(primary_counts) != int(stats["primary_values"]):
    raise SystemExit("primary_values statistic mismatch")
if sum(primary_bytes) != int(stats["primary_sample_bytes"]):
    raise SystemExit("primary_sample_bytes statistic mismatch")
if statistics.median(primary_counts) < min_median_values:
    raise SystemExit(f"median primary values below floor: {statistics.median(primary_counts)}")
if sum(primary_bytes) < min_primary_bytes:
    raise SystemExit(f"primary bytes below floor: {sum(primary_bytes)} < {min_primary_bytes}")

print(
    f"verified_primary_samples={len(primary_rows)} auxiliary_samples={len(aux_rows)} "
    f"primary_values={sum(primary_counts)} primary_sample_bytes={sum(primary_bytes)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
