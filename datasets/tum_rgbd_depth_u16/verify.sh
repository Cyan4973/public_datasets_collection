#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="tum_rgbd_depth_u16"
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
from array import array
from pathlib import Path

DATASET_ID = "tum_rgbd_depth_u16"
SERIES_ID = "tum_rgbd_depth_u16"
MIN_FRAMES = int(os.environ.get("TUM_MIN_FRAMES", "50"))
MAX_PRIMARY_BYTES = int(os.environ.get("TUM_MAX_PRIMARY_BYTES", "1000000000"))
import sys

data_root = Path(os.environ["DATA_ROOT"])
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
if len(rows) < MIN_FRAMES:
    raise SystemExit(f"expected >= {MIN_FRAMES} depth frames, found {len(rows)}")

seen = set()
primary_bytes = 0
for row in rows:
    if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
        raise SystemExit(f"unexpected row identity: {row}")
    if row.get("numeric_kind") != "uint" or int(row.get("bit_width", 0)) != 16 or int(row.get("element_size_bytes", 0)) != 2:
        raise SystemExit(f"unexpected representation: {row}")
    if row.get("endianness") != "little" or row.get("sample_geometry") != "2d_raster" or int(row.get("sample_rank", 0)) != 2:
        raise SystemExit(f"unexpected geometry: {row}")
    if row.get("natural_record_kind") != "tum_rgbd_depth_frame":
        raise SystemExit(f"unexpected natural boundary: {row}")
    shape = row.get("sample_shape")
    if not isinstance(shape, list) or len(shape) != 2 or shape[0] * shape[1] != int(row["value_count"]):
        raise SystemExit(f"shape/value mismatch: {row}")
    path = data_root / row["sample_path"]
    if row["sample_path"] in seen:
        raise SystemExit(f"duplicate sample path: {row['sample_path']}")
    seen.add(row["sample_path"])
    expected_bytes = int(row["sample_size_bytes"])
    if expected_bytes != int(row["value_count"]) * 2:
        raise SystemExit(f"byte/value mismatch: {path}")
    if not path.is_file() or path.stat().st_size != expected_bytes:
        raise SystemExit(f"size mismatch: {path}")
    a = array("H")
    a.frombytes(path.read_bytes())
    if sys.byteorder == "big":
        a.byteswap()
    if len(a) != int(row["value_count"]):
        raise SystemExit(f"value count mismatch: {path}")
    vmin, vmax = min(a), max(a)
    if vmin == vmax:
        raise SystemExit(f"constant frame: {path}")
    if int(row["min"]) != vmin or int(row["max"]) != vmax:
        raise SystemExit(f"index min/max mismatch: {path}")
    primary_bytes += expected_bytes

if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if int(stats.get("frames", -1)) != len(rows) or int(stats.get("primary_bytes", -1)) != primary_bytes:
    raise SystemExit("stats/index mismatch")

print(f"verified_frames={len(rows)} shape={rows[0]['sample_shape']} primary_bytes={primary_bytes}")
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
