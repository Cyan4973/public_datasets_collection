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
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
import shutil
import struct
from pathlib import Path

DATASET_ID = "skadi_srtm_hgt"
SERIES_ID = "skadi_elevation"
TILE = "N37W122"
GRID_WIDTH = 3601
GRID_HEIGHT = 3601
TILE_VALUES = GRID_WIDTH * GRID_HEIGHT
TILE_BYTES = TILE_VALUES * 2
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


source = download_dir / f"{TILE}.hgt.gz"
if not source.exists():
    raise SystemExit(f"missing local source: {source}; run datasets/skadi_srtm_hgt/download.sh first")

raw = gzip.decompress(source.read_bytes())
if len(raw) != TILE_BYTES:
    raise SystemExit(f"unexpected decoded HGT size: {len(raw)}")

out_dir = samples_dir / SERIES_ID
if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

# HGT stores big-endian int16 values. The repository sample convention is
# little-endian homogeneous numeric arrays.
converted = bytearray(TILE_BYTES)
converted[0::2] = raw[1::2]
converted[1::2] = raw[0::2]
out = out_dir / f"{TILE}.bin"
out.write_bytes(converted)

size = out.stat().st_size
if size != TILE_BYTES:
    raise SystemExit(f"whole-tile size mismatch: expected {TILE_BYTES} got {size}")
if size > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {size}")

prefix_values = struct.unpack("<" + "h" * 10_000, out.read_bytes()[:20_000])
if len(set(prefix_values)) <= 1:
    raise SystemExit("degenerate constant tile prefix")
if all(value == -32768 for value in prefix_values):
    raise SystemExit("degenerate all-void tile prefix")

row = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "role": "primary",
    "sample_path": rel(out),
    "numeric_kind": "int",
    "bit_width": 16,
    "endianness": "little",
    "element_size_bytes": 2,
    "sample_size_bytes": size,
    "value_count": TILE_VALUES,
    "sample_geometry": "2d_raster",
    "sample_rank": 2,
    "sample_shape": [GRID_HEIGHT, GRID_WIDTH],
    "sample_axes": ["y", "x"],
    "tile": TILE,
    "grid_width": GRID_WIDTH,
    "grid_height": GRID_HEIGHT,
}
stats = {
    "dataset_id": DATASET_ID,
    "tile": TILE,
    "source_file": source.name,
    "source_bytes": source.stat().st_size,
    "sample_count": 1,
    "primary_values": TILE_VALUES,
    "primary_bytes": size,
    "grid_width": GRID_WIDTH,
    "grid_height": GRID_HEIGHT,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (filter_dir / "inventory.tsv").open("w", encoding="utf-8") as fh:
    fh.write("tile\tgrid_height\tgrid_width\tvalues\tbytes\tsource_file\tsource_bytes\n")
    fh.write(f"{TILE}\t{GRID_HEIGHT}\t{GRID_WIDTH}\t{TILE_VALUES}\t{size}\t{source.name}\t{source.stat().st_size}\n")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    fh.write(json.dumps(row, sort_keys=True) + "\n")

print(f"built_samples=1 primary_values={TILE_VALUES} primary_bytes={size} source_bytes={source.stat().st_size}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
