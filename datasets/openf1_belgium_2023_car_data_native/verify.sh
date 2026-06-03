#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openf1_belgium_2023_car_data_native"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
import json
import os
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])

raw_files = sorted(download_dir.glob("car_data_s9135_d*.json"))
if not raw_files:
    raise SystemExit("missing raw OpenF1 car_data files")

stats_path = filter_dir / "ingest_stats.json"
index_path = index_dir / "samples.jsonl"
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
driver_count = len(stats["drivers"])
if driver_count != len(raw_files):
    raise SystemExit(f"driver count mismatch: stats={driver_count} raw={len(raw_files)}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
expected_series = {
    "openf1_speed": (16, 2),
    "openf1_rpm": (16, 2),
    "openf1_throttle": (8, 1),
    "openf1_brake": (8, 1),
    "openf1_n_gear": (8, 1),
    "openf1_drs": (8, 1),
}
expected_row_count = len(raw_files) * len(expected_series)
if len(rows) != expected_row_count:
    raise SystemExit(f"unexpected index row count: {len(rows)} != {expected_row_count}")

for row in rows:
    series_id = row["series_id"]
    if series_id not in expected_series:
        raise SystemExit(f"unexpected series id: {series_id}")
    bit_width, element_size = expected_series[series_id]
    if row["dataset_id"] != "openf1_belgium_2023_car_data_native":
        raise SystemExit(f"unexpected dataset id: {row}")
    if row["bit_width"] != bit_width or row["element_size_bytes"] != element_size or row["endianness"] != "little":
        raise SystemExit(f"unexpected metadata: {row}")
    sample_path = data_root / row["sample_path"]
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    if sample_path.stat().st_size != row["sample_size_bytes"]:
        raise SystemExit(f"sample size mismatch: {sample_path}")
    if row["sample_size_bytes"] != row["value_count"] * element_size:
        raise SystemExit(f"bad element size accounting: {row}")

print(f"verified_samples={len(rows)}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
