#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_themis_ir_mosaic_u8"
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
from collections import Counter
from pathlib import Path

DATASET_ID = "nasa_pds_themis_ir_mosaic_u8"
SERIES_ID = "themis_ir_mosaic_pixels_u8"
MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if len(rows) != 2:
    raise SystemExit(f"expected exactly 2 bounded THEMIS mosaic samples, found {len(rows)}")

sizes = []
value_counts = []
shapes = []
for row in rows:
    if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID:
        raise SystemExit(f"unexpected dataset/series row: {row}")
    if row.get("role") != "primary" or row["numeric_kind"] != "uint" or int(row["bit_width"]) != 8:
        raise SystemExit(f"unexpected numeric row: {row}")
    if int(row["element_size_bytes"]) != 1:
        raise SystemExit(f"unexpected element size: {row}")
    if row.get("sample_geometry") != "2d_raster" or int(row.get("sample_rank", 0)) != 2:
        raise SystemExit(f"unexpected geometry: {row}")
    if row.get("sample_format") != "raw homogeneous uint8 array copied from TIFF pixel plane":
        raise SystemExit(f"unexpected sample format: {row}")
    if row.get("natural_record_kind") != "themis_controlled_ir_mosaic":
        raise SystemExit(f"unexpected natural record kind: {row}")
    if row.get("min") == row.get("max"):
        raise SystemExit(f"constant raster metadata: {row}")
    path = data_root / row["sample_path"]
    payload = path.read_bytes()
    if len(payload) != int(row["sample_size_bytes"]) or len(payload) != int(row["value_count"]):
        raise SystemExit(f"size/count mismatch: {path}")
    histogram = Counter(payload)
    if len(histogram) <= 1:
        raise SystemExit(f"constant raster rejected: {path}")
    if histogram.most_common(1)[0][1] / len(payload) > 0.999:
        raise SystemExit(f"near-constant raster rejected: {path}")
    if min(histogram) != int(row["min"]) or max(histogram) != int(row["max"]):
        raise SystemExit(f"min/max metadata mismatch: {path}")
    sizes.append(len(payload))
    value_counts.append(int(row["value_count"]))
    shapes.append(tuple(row["sample_shape"]))

primary_bytes = sum(sizes)
primary_values = sum(value_counts)
median_values = statistics.median(value_counts)
if primary_values < MIN_PRIMARY_VALUES:
    raise SystemExit(f"primary_values below floor: {primary_values}")
if primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary_bytes below floor: {primary_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary_bytes exceeds cap: {primary_bytes}")
if primary_bytes != int(stats["total_primary_bytes"]):
    raise SystemExit("stats/index primary byte mismatch")

print(
    f"verified_rows={len(rows)} primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_values={int(median_values)} size_range={min(sizes)}/{int(statistics.median(sizes))}/{max(sizes)} "
    f"unique_shapes={len(set(shapes))}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
