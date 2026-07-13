#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="sentinel1_grd_measurement_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
FILTER_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export DATA_ROOT FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
import struct
from pathlib import Path

DATASET_ID = "sentinel1_grd_measurement_u16"
ALLOWED_SERIES = {
    "sentinel1_grd_vv_dn_u16": "VV",
    "sentinel1_grd_vh_dn_u16": "VH",
    "sentinel1_grd_hh_dn_u16": "HH",
    "sentinel1_grd_hv_dn_u16": "HV",
}
MIN_PRIMARY_VALUES = int(os.environ.get("SENTINEL1_MIN_PRIMARY_VALUES", "10000"))
MIN_PRIMARY_BYTES = int(os.environ.get("SENTINEL1_MIN_PRIMARY_BYTES", str(100 * 1024)))
MIN_MEDIAN_VALUES = int(os.environ.get("SENTINEL1_MIN_MEDIAN_VALUES", "1000"))
MIN_SAMPLE_COUNT = int(os.environ.get("SENTINEL1_MIN_SAMPLE_COUNT", "2"))
MAX_PRIMARY_BYTES = int(os.environ.get("SENTINEL1_MAX_PRIMARY_BYTES", "1000000000"))

data_root = Path(os.environ["DATA_ROOT"])
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if len(rows) < MIN_SAMPLE_COUNT:
    raise SystemExit(f"expected at least {MIN_SAMPLE_COUNT} Sentinel-1 measurement samples, found {len(rows)}")

sizes = []
values = []
series_counts: dict[str, int] = {}
scene_ids = set()
shapes = set()
for row in rows:
    sid = row.get("series_id")
    if row.get("dataset_id") != DATASET_ID or sid not in ALLOWED_SERIES:
        raise SystemExit(f"unexpected dataset/series row: {row}")
    if row.get("polarization") != ALLOWED_SERIES[sid]:
        raise SystemExit(f"series/polarization mismatch: {row}")
    if row.get("role") != "primary" or row.get("numeric_kind") != "uint" or int(row.get("bit_width", 0)) != 16:
        raise SystemExit(f"unexpected numeric row: {row}")
    if int(row.get("element_size_bytes", 0)) != 2:
        raise SystemExit(f"unexpected element size: {row}")
    if row.get("sample_geometry") != "2d_raster" or int(row.get("sample_rank", 0)) != 2:
        raise SystemExit(f"unexpected geometry: {row}")
    if row.get("natural_record_kind") != "sentinel1_grd_measurement_tiff":
        raise SystemExit(f"unexpected natural boundary: {row}")
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
    if min(sampled) < 0 or max(sampled) > 65535:
        raise SystemExit(f"value outside uint16 range: {path}")
    sizes.append(expected_bytes)
    values.append(expected_values)
    series_counts[sid] = series_counts.get(sid, 0) + 1
    scene_ids.add(row.get("scene_id"))
    shapes.add(tuple(row["sample_shape"]))

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
if set(stats.get("series_total_bytes", {})) != set(series_counts):
    raise SystemExit("stats/index series mismatch")

print(
    f"verified_rows={len(rows)} scenes={len(scene_ids)} series={','.join(sorted(series_counts))} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_values={int(median_values)} size_range={min(sizes)}/{int(statistics.median(sizes))}/{max(sizes)} "
    f"unique_shapes={len(shapes)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
