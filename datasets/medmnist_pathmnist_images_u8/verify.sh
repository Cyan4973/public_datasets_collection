#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="medmnist_pathmnist_images_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
from pathlib import Path

DATASET_ID = "medmnist_pathmnist_images_u8"
PRIMARY_SERIES = {"pathmnist_images"}
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")

def inspect(path: Path) -> tuple[int, int]:
    size = 0
    distinct = set()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            size += len(chunk)
            distinct.update(chunk)
    return size, len(distinct)

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
primary_counts = []
primary_bytes = 0
expected_samples = 107180
expected_sample_size = 28 * 28 * 3
for row in rows:
    if row["dataset_id"] != DATASET_ID or row["numeric_kind"] != "uint" or row["bit_width"] != 8:
        raise SystemExit(f"unexpected row: {row}")
    path = data_root / row["sample_path"]
    if not path.exists():
        raise SystemExit(f"missing sample: {path}")
    size, distinct = inspect(path)
    if size != row["sample_size_bytes"] or size != row["value_count"]:
        raise SystemExit(f"size/count mismatch: {path}")
    if distinct < 2:
        raise SystemExit(f"degenerate constant sample: {path}")
    if row["series_id"] in PRIMARY_SERIES:
        if row["value_count"] != expected_sample_size:
            raise SystemExit(f"unexpected image sample size: {row}")
        primary_counts.append(row["value_count"])
        primary_bytes += row["sample_size_bytes"]

if not primary_counts:
    raise SystemExit("no primary samples")
if primary_bytes < 100 * 1024:
    raise SystemExit("primary 8-bit payload below 100 KiB byte floor")
if sum(primary_counts) < 10000:
    raise SystemExit("primary payload below 10,000-value floor")
if statistics.median(primary_counts) < 1000:
    raise SystemExit("primary median sample size below floor")
if len(primary_counts) != expected_samples:
    raise SystemExit(f"unexpected primary sample count: {len(primary_counts)} expected {expected_samples}")

print(f"verified_rows={len(rows)} primary_samples={len(primary_counts)} primary_values={sum(primary_counts)} primary_bytes={primary_bytes}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
