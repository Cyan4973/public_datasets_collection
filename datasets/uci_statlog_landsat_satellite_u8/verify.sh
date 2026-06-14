#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_statlog_landsat_satellite_u8"
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

DATASET_ID = "uci_statlog_landsat_satellite_u8"
PRIMARY_SERIES = {"landsat_spectral_features"}
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")

def inspect(path: Path, series_id: str) -> tuple[int, int]:
    size = 0
    distinct = set()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            size += len(chunk)
            distinct.update(chunk)
            if series_id == "landsat_class_labels" and any(value < 1 or value > 7 for value in chunk):
                raise SystemExit("land-cover label outside 1..7")
    return size, len(distinct)

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
primary_counts = []
primary_bytes = 0
for row in rows:
    if row["dataset_id"] != DATASET_ID:
        raise SystemExit(f"unexpected dataset_id: {row}")
    if row["numeric_kind"] != "uint" or row["bit_width"] != 8 or row["element_size_bytes"] != 1:
        raise SystemExit(f"non-u8 row: {row}")
    path = data_root / row["sample_path"]
    if not path.exists():
        raise SystemExit(f"missing sample: {path}")
    size, distinct = inspect(path, row["series_id"])
    if size != row["sample_size_bytes"] or size != row["value_count"]:
        raise SystemExit(f"size/count mismatch: {path}")
    if distinct < 2:
        raise SystemExit(f"degenerate constant sample: {path}")
    if row["series_id"] in PRIMARY_SERIES:
        primary_counts.append(row["value_count"])
        primary_bytes += row["sample_size_bytes"]

if not primary_counts:
    raise SystemExit("no primary samples")
if sum(primary_counts) < 10000 and primary_bytes < 100000:
    raise SystemExit("primary payload below aggregate floor")
if statistics.median(primary_counts) < 1000:
    raise SystemExit("primary median sample size below floor")

print(f"verified_rows={len(rows)} primary_values={sum(primary_counts)} primary_bytes={primary_bytes}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
