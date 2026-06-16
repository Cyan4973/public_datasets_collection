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
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

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
import struct
from pathlib import Path

DATASET_ID = "skadi_srtm_hgt"
SERIES_ID = "skadi_elevation"
TILE = "N37W122"
GRID_WIDTH = 3601
GRID_HEIGHT = 3601
TILE_VALUES = GRID_WIDTH * GRID_HEIGHT
TILE_BYTES = TILE_VALUES * 2

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != 1:
    raise SystemExit(f"expected one whole-tile sample, got {len(rows)}")
row = rows[0]
if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID or row.get("role") != "primary":
    raise SystemExit(f"unexpected row identity: {row}")
if row.get("tile") != TILE:
    raise SystemExit(f"unexpected tile: {row}")
if row["numeric_kind"] != "int" or int(row["bit_width"]) != 16 or row["endianness"] != "little":
    raise SystemExit(f"unexpected numeric representation: {row}")
if row.get("sample_geometry") != "2d_raster" or int(row.get("sample_rank", 0)) != 2:
    raise SystemExit(f"unexpected sample geometry: {row}")
if row.get("sample_shape") != [GRID_HEIGHT, GRID_WIDTH] or row.get("sample_axes") != ["y", "x"]:
    raise SystemExit(f"unexpected sample shape/axes: {row}")
if int(row["value_count"]) != TILE_VALUES or int(row["sample_size_bytes"]) != TILE_BYTES:
    raise SystemExit(f"unexpected sample dimensions: {row}")

sample_path = data_root / row["sample_path"]
if not sample_path.is_file():
    raise SystemExit(f"missing sample file: {sample_path}")
if sample_path.stat().st_size != TILE_BYTES:
    raise SystemExit(f"size mismatch: {sample_path}")
prefix_values = struct.unpack("<" + "h" * 10_000, sample_path.read_bytes()[:20_000])
if len(set(prefix_values)) <= 1:
    raise SystemExit("degenerate constant tile prefix")
if all(value == -32768 for value in prefix_values):
    raise SystemExit("degenerate all-void tile prefix")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats.get("dataset_id") != DATASET_ID or int(stats.get("sample_count", 0)) != 1:
    raise SystemExit(f"unexpected stats: {stats}")
if int(stats.get("primary_values", 0)) != TILE_VALUES or int(stats.get("primary_bytes", 0)) != TILE_BYTES:
    raise SystemExit(f"stats/sample mismatch: {stats}")

print(f"verified_samples=1 primary_values={TILE_VALUES} primary_bytes={TILE_BYTES} source_bytes={stats.get('source_bytes', 0)}")
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
