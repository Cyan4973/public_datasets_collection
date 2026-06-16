#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sentinel2_l2a_reflectance_cogs_u16"
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
import struct
from pathlib import Path

DATASET_ID = "sentinel2_l2a_reflectance_cogs_u16"
SERIES_ID = "sentinel2_l2a_reflectance_pixels_u16"
MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
EXPECTED_BANDS = {"blue_10m", "rededge1_20m", "coastal_60m"}

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if len(rows) < 6:
    raise SystemExit(f"expected at least 6 Sentinel-2 band samples, found {len(rows)}")
scene_ids = {row.get("scene_id") for row in rows}
band_labels = {row.get("band_label") for row in rows}
if len(scene_ids) < 2:
    raise SystemExit(f"expected at least 2 scenes, found {len(scene_ids)}")
if band_labels != EXPECTED_BANDS:
    raise SystemExit(f"unexpected band set: {sorted(band_labels)}")

sizes = []
values = []
shapes = []
for row in rows:
    if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID:
        raise SystemExit(f"unexpected dataset/series row: {row}")
    if row.get("role") != "primary" or row["numeric_kind"] != "uint" or int(row["bit_width"]) != 16:
        raise SystemExit(f"unexpected numeric row: {row}")
    if int(row["element_size_bytes"]) != 2:
        raise SystemExit(f"unexpected element size: {row}")
    if row.get("sample_geometry") != "2d_raster" or int(row.get("sample_rank", 0)) != 2:
        raise SystemExit(f"unexpected geometry: {row}")
    path = data_root / row["sample_path"]
    expected_bytes = int(row["sample_size_bytes"])
    expected_values = int(row["value_count"])
    if path.stat().st_size != expected_bytes or expected_bytes != expected_values * 2:
        raise SystemExit(f"size/count mismatch: {path}")
    endian = "<" if row["endianness"] == "little" else ">"
    sample_count = min(expected_values, 200_000)
    with path.open("rb") as fh:
        sampled_bytes = fh.read(sample_count * 2)
    sampled = struct.unpack(endian + "H" * sample_count, sampled_bytes)
    if len(set(sampled)) <= 1:
        raise SystemExit(f"constant prefix rejected: {path}")
    if max(sampled) > 65535 or min(sampled) < 0:
        raise SystemExit(f"value outside uint16 range: {path}")
    sizes.append(expected_bytes)
    values.append(expected_values)
    shapes.append(tuple(row["sample_shape"]))

primary_bytes = sum(sizes)
primary_values = sum(values)
median_values = statistics.median(values)
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
if len(set(shapes)) < 3:
    raise SystemExit(f"expected mixed native resolutions, found shapes={sorted(set(shapes))}")

print(
    f"verified_rows={len(rows)} scenes={len(scene_ids)} primary_values={primary_values} "
    f"primary_bytes={primary_bytes} median_values={int(median_values)} "
    f"size_range={min(sizes)}/{int(statistics.median(sizes))}/{max(sizes)} unique_shapes={len(set(shapes))}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
