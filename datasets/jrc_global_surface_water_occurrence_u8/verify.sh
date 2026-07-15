#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="jrc_global_surface_water_occurrence_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
from pathlib import Path

DATASET_ID = "jrc_global_surface_water_occurrence_u8"
SERIES_ID = "global_surface_water_occurrence_u8"
MIN_SAMPLES = 12
MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
ALLOWED_VALUES = set(range(101)) | {255}

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
primary = [row for row in rows if row.get("role", "primary") == "primary"]
if len(primary) < MIN_SAMPLES:
    raise SystemExit(f"only {len(primary)} primary samples < {MIN_SAMPLES}")
if {row["series_id"] for row in primary} != {SERIES_ID}:
    raise SystemExit(f"unexpected series: {sorted({row['series_id'] for row in primary})}")

counts = []
sizes = []
nonconstant = 0
for row in primary:
    if row["dataset_id"] != DATASET_ID:
        raise SystemExit(f"unexpected dataset row: {row}")
    if row["numeric_kind"] != "uint" or int(row["bit_width"]) != 8 or int(row["element_size_bytes"]) != 1:
        raise SystemExit(f"not uint8: {row['sample_path']}")
    if row.get("sample_format") != "raw homogeneous uint8 occurrence grid":
        raise SystemExit(f"unexpected sample format: {row}")
    if row.get("sample_geometry") != "2d_occurrence_raster_tile" or int(row.get("sample_rank", 0)) != 2:
        raise SystemExit(f"unexpected sample geometry: {row}")
    path = root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample {row['sample_path']}")
    payload = path.read_bytes()
    if len(payload) != int(row["sample_size_bytes"]) or len(payload) != int(row["value_count"]):
        raise SystemExit(f"size mismatch {row['sample_path']}")
    unknown = set(payload) - ALLOWED_VALUES
    if unknown:
        raise SystemExit(f"unexpected occurrence values in {row['sample_path']}: {sorted(unknown)[:10]}")
    if len(set(payload)) > 1:
        nonconstant += 1
    if payload.count(255) / len(payload) > 0.995:
        raise SystemExit(f"nodata-dominated sample: {row['sample_path']}")
    counts.append(int(row["value_count"]))
    sizes.append(int(row["sample_size_bytes"]))

if nonconstant != len(primary):
    raise SystemExit(f"constant samples found: nonconstant={nonconstant} total={len(primary)}")
total_values = sum(counts)
total_bytes = sum(sizes)
median_values = statistics.median(counts)
if total_values < MIN_PRIMARY_VALUES:
    raise SystemExit(f"primary values below floor: {total_values}")
if total_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {total_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")
if int(stats["primary_sample_bytes"]) != total_bytes:
    raise SystemExit("stats/index byte mismatch")

print(
    f"verified series={SERIES_ID} samples={len(primary)} "
    f"median_values={int(median_values)} total_values={total_values} total_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
