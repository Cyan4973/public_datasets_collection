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
from array import array
from pathlib import Path

DATASET_ID = "skadi_srtm_hgt"
SERIES_ID = "skadi_elevation"
TILE = "N37W122"
GRID_WIDTH = 3601
GRID_HEIGHT = 3601
TILE_VALUES = GRID_WIDTH * GRID_HEIGHT
TILE_BYTES = TILE_VALUES * 2
VOID = -32768
# One SRTM HGT tile is a single 3601x3601 raster -- far too large for one training
# sample. Split it into full-width row-band strips (the natural row-major sub-unit
# of an HGT file), mirroring the downstream srtm_skadi_elevation family.
STRIP_ROWS = int(os.environ.get("SKADI_STRIP_ROWS", "54"))
MIN_SAMPLE_COUNT = int(os.environ.get("SKADI_MIN_SAMPLE_COUNT", "8"))
MAX_PRIMARY_BYTES = int(os.environ.get("SKADI_MAX_PRIMARY_BYTES", "1000000000"))

if STRIP_ROWS < 1:
    raise SystemExit(f"SKADI_STRIP_ROWS must be >= 1, got {STRIP_ROWS}")

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

# HGT stores big-endian int16 values; the repository sample convention is
# little-endian homogeneous numeric arrays. Byte-swap the whole raster once, then
# slice contiguous row bands out of it.
converted = bytearray(TILE_BYTES)
converted[0::2] = raw[1::2]
converted[1::2] = raw[0::2]

row_stride = GRID_WIDTH * 2
rows = []
records = []
total_bytes = 0
total_values = 0
dropped_flat = 0
dropped_void = 0

for row_start in range(0, GRID_HEIGHT, STRIP_ROWS):
    row_end = min(row_start + STRIP_ROWS, GRID_HEIGHT)
    strip_height = row_end - row_start
    strip = bytes(converted[row_start * row_stride : row_end * row_stride])
    vals = array("h")
    vals.frombytes(strip)
    if vals.count(vals[0]) == len(vals):  # constant strip is degenerate for training
        if vals[0] == VOID:
            dropped_void += 1
        else:
            dropped_flat += 1
        continue
    sample_index = len(rows) + 1
    out = out_dir / f"{TILE}_rows_{row_start:04d}_{row_end - 1:04d}.bin"
    out.write_bytes(strip)
    total_bytes += len(strip)
    total_values += len(vals)
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes exceed cap: {total_bytes}")
    void_count = vals.count(VOID)
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": rel(out),
        "numeric_kind": "int",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": len(strip),
        "value_count": len(vals),
        "sample_geometry": "2d_raster",
        "sample_rank": 2,
        "sample_shape": [strip_height, GRID_WIDTH],
        "sample_axes": ["y", "x"],
        "natural_record_kind": "srtm_hgt_row_band",
        "tile": TILE,
        "row_start": row_start,
        "row_end": row_end,
        "grid_width": GRID_WIDTH,
        "grid_height": GRID_HEIGHT,
        "void_count": void_count,
    }
    rows.append(row)
    records.append(
        {
            "tile": TILE,
            "sample_path": row["sample_path"],
            "row_start": row_start,
            "row_end": row_end,
            "sample_bytes": len(strip),
            "value_count": len(vals),
            "shape": [strip_height, GRID_WIDTH],
            "void_count": void_count,
            "min_value": min(vals),
            "max_value": max(vals),
        }
    )

if dropped_flat or dropped_void:
    print(f"dropped strips: flat_constant={dropped_flat} all_void={dropped_void}")

if len(rows) < MIN_SAMPLE_COUNT:
    raise SystemExit(f"expected at least {MIN_SAMPLE_COUNT} row-band strips, built {len(rows)}")

stats = {
    "dataset_id": DATASET_ID,
    "tile": TILE,
    "source_file": source.name,
    "source_bytes": source.stat().st_size,
    "sample_count": len(rows),
    "strip_rows": STRIP_ROWS,
    "primary_values": total_values,
    "primary_bytes": total_bytes,
    "grid_width": GRID_WIDTH,
    "grid_height": GRID_HEIGHT,
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (filter_dir / "inventory.tsv").open("w", encoding="utf-8") as fh:
    fh.write("tile\trow_start\trow_end\tvalues\tbytes\n")
    for record in records:
        fh.write(f"{record['tile']}\t{record['row_start']}\t{record['row_end']}\t{record['value_count']}\t{record['sample_bytes']}\n")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(f"built_samples={len(rows)} strip_rows={STRIP_ROWS} primary_values={total_values} primary_bytes={total_bytes} source_bytes={source.stat().st_size}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
