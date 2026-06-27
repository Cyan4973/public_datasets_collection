#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="wwpdb_mmcif_atom_coords_f32"
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
import math
import os
import statistics
import struct
from pathlib import Path

MIN_SAMPLES = 2
MIN_MEDIAN_VALUES = 1_000
MIN_TOTAL_VALUES = 10_000
MIN_TOTAL_BYTES = 102_400
MAX_PRIMARY_BYTES = 1_000_000_000
FAMILY = "atom_cartesian_xyz_f32"

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
primary = [r for r in rows if r.get("role", "primary") == "primary"]
if len(primary) < MIN_SAMPLES:
    raise SystemExit(f"only {len(primary)} primary samples < {MIN_SAMPLES}")
if {r["series_id"] for r in primary} != {FAMILY}:
    raise SystemExit(f"unexpected families: {sorted({r['series_id'] for r in primary})}")

counts = [int(r["value_count"]) for r in primary]
total_values = sum(counts)
total_bytes = sum(int(r["sample_size_bytes"]) for r in primary)
median_values = statistics.median(counts)
if total_values < MIN_TOTAL_VALUES and total_bytes < MIN_TOTAL_BYTES:
    raise SystemExit(f"below aggregate floor: values={total_values} bytes={total_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")

seen_paths: set[str] = set()
nonconstant = 0
for row in primary:
    if row["sample_path"] in seen_paths:
        raise SystemExit(f"duplicate sample path: {row['sample_path']}")
    seen_paths.add(row["sample_path"])
    if row["numeric_kind"] != "float" or int(row["bit_width"]) != 32 or int(row["element_size_bytes"]) != 4:
        raise SystemExit(f"not float32: {row['sample_path']}")
    if row.get("sample_geometry") != "3d_point_set_xyz" or int(row.get("sample_rank", 0)) != 2:
        raise SystemExit(f"unexpected geometry: {row['sample_path']}")
    shape = row.get("sample_shape")
    if not isinstance(shape, list) or len(shape) != 2 or int(shape[1]) != 3:
        raise SystemExit(f"bad xyz shape: {row['sample_path']}")
    if int(shape[0]) * 3 != int(row["value_count"]):
        raise SystemExit(f"atom/value count mismatch: {row['sample_path']}")
    p = root / row["sample_path"]
    if not p.is_file():
        raise SystemExit(f"missing sample {row['sample_path']}")
    data = p.read_bytes()
    if len(data) != int(row["sample_size_bytes"]) or len(data) != int(row["value_count"]) * 4:
        raise SystemExit(f"size mismatch {row['sample_path']}")
    floats = struct.iter_unpack("<f", data)
    sample_min = math.inf
    sample_max = -math.inf
    checked = 0
    for (value,) in floats:
        if not math.isfinite(value):
            raise SystemExit(f"non-finite coordinate in {row['sample_path']}")
        sample_min = min(sample_min, value)
        sample_max = max(sample_max, value)
        checked += 1
    if checked != int(row["value_count"]):
        raise SystemExit(f"value count unpack mismatch: {row['sample_path']}")
    if sample_min < sample_max:
        nonconstant += 1
if nonconstant != len(primary):
    raise SystemExit(f"constant primary samples found: nonconstant={nonconstant} total={len(primary)}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if int(stats["primary_sample_bytes"]) != total_bytes or int(stats["primary_values"]) != total_values:
    raise SystemExit("ingest stats do not match index totals")

print(
    f"verified family={FAMILY} samples={len(primary)} "
    f"median_values={int(median_values)} total_values={total_values} total_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
