#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="skadi_srtm_hgt"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
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
from array import array
from pathlib import Path

DATASET_ID = "skadi_srtm_hgt"
SERIES_ID = "skadi_elevation"
TILE = "N37W122"
GRID_WIDTH = 3601
GRID_HEIGHT = 3601
VOID = -32768
MIN_SAMPLE_COUNT = int(os.environ.get("SKADI_MIN_SAMPLE_COUNT", "8"))
MAX_PRIMARY_BYTES = int(os.environ.get("SKADI_MAX_PRIMARY_BYTES", "1000000000"))

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) < MIN_SAMPLE_COUNT:
    raise SystemExit(f"expected at least {MIN_SAMPLE_COUNT} row-band strips, got {len(rows)}")

sizes = []
values = []
shapes = set()
rows_covered = 0
for row in rows:
    if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID or row.get("role") != "primary":
        raise SystemExit(f"unexpected row identity: {row}")
    if row.get("tile") != TILE:
        raise SystemExit(f"unexpected tile: {row}")
    if row["numeric_kind"] != "int" or int(row["bit_width"]) != 16 or row["endianness"] != "little":
        raise SystemExit(f"unexpected numeric representation: {row}")
    if row.get("sample_geometry") != "2d_raster" or int(row.get("sample_rank", 0)) != 2:
        raise SystemExit(f"unexpected sample geometry: {row}")
    if row.get("natural_record_kind") != "srtm_hgt_row_band":
        raise SystemExit(f"unexpected natural boundary: {row}")
    shape = row.get("sample_shape")
    if not isinstance(shape, list) or len(shape) != 2 or shape[1] != GRID_WIDTH:
        raise SystemExit(f"unexpected sample shape: {row}")
    strip_height = int(shape[0])
    if strip_height < 1 or strip_height > GRID_HEIGHT:
        raise SystemExit(f"unexpected strip height: {row}")
    if int(row["value_count"]) != strip_height * GRID_WIDTH or int(row["sample_size_bytes"]) != strip_height * GRID_WIDTH * 2:
        raise SystemExit(f"unexpected sample dimensions: {row}")
    path = data_root / row["sample_path"]
    if not path.is_file() or path.stat().st_size != int(row["sample_size_bytes"]):
        raise SystemExit(f"size mismatch: {path}")
    vals = array("h")
    vals.frombytes(path.read_bytes())
    if vals.count(vals[0]) == len(vals):
        raise SystemExit(f"degenerate constant strip: {path}")
    if min(vals) < -32768 or max(vals) > 32767:
        raise SystemExit(f"value outside int16 range: {path}")
    sizes.append(int(row["sample_size_bytes"]))
    values.append(int(row["value_count"]))
    shapes.add(tuple(shape))
    rows_covered += strip_height

primary_bytes = sum(sizes)
if rows_covered > GRID_HEIGHT:
    raise SystemExit(f"covered rows exceed tile height: {rows_covered} > {GRID_HEIGHT}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary_bytes exceeds cap: {primary_bytes}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats.get("dataset_id") != DATASET_ID or int(stats.get("sample_count", 0)) != len(rows):
    raise SystemExit(f"stats/sample count mismatch: {stats.get('sample_count')} vs {len(rows)}")
if int(stats.get("primary_bytes", 0)) != primary_bytes:
    raise SystemExit(f"stats/index primary byte mismatch: {stats.get('primary_bytes')} vs {primary_bytes}")

print(
    f"verified_rows={len(rows)} rows_covered={rows_covered}/{GRID_HEIGHT} primary_values={sum(values)} "
    f"primary_bytes={primary_bytes} median_values={int(statistics.median(values))} "
    f"size_range={min(sizes)}/{int(statistics.median(sizes))}/{max(sizes)} unique_shapes={len(shapes)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
