#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_open_buildings_v3_s2_073_geometry_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR"

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
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
filter_dir = Path(os.environ["FILTER_DIR"])
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = filter_dir / "ingest_stats.json"

if not index_path.is_file():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats: {stats_path}")

required_fields = {
    "centroid_lat_lon_f32",
    "area_in_meters_f32",
    "confidence_f32",
    "polygon_vertex_lon_lat_f32",
}
seen_fields: set[str] = set()
rows = []
total_bytes = 0
total_values = 0
for line in index_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("dataset_id") != "google_open_buildings_v3_s2_073_geometry_f32":
        raise SystemExit(f"wrong dataset_id: {row.get('dataset_id')}")
    if row.get("family") != "open_buildings_v3_s2_073_geometry_f32":
        raise SystemExit(f"wrong family: {row.get('family')}")
    if row.get("numeric_kind") != "float" or row.get("bit_width") != 32:
        raise SystemExit(f"unexpected numeric representation: {row}")
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {path}")
    size = path.stat().st_size
    if size != row["sample_size_bytes"]:
        raise SystemExit(f"size mismatch for {path}: {size} != {row['sample_size_bytes']}")
    if size % row["element_size_bytes"] != 0:
        raise SystemExit(f"alignment mismatch: {path}")
    if size // row["element_size_bytes"] != row["value_count"]:
        raise SystemExit(f"value count mismatch: {path}")
    if row["min_value"] == row["max_value"]:
        raise SystemExit(f"constant sample was accepted: {path}")
    seen_fields.add(row["source_field_name"])
    total_bytes += size
    total_values += int(row["value_count"])
    rows.append(row)

stats = json.loads(stats_path.read_text(encoding="utf-8"))
missing = sorted(required_fields - seen_fields)
if missing:
    raise SystemExit(f"missing required samples: {missing}")
if stats["buildings"] < 500_000:
    raise SystemExit(f"too few buildings: {stats['buildings']}")
if stats["polygon_vertex_pairs"] < 2_500_000:
    raise SystemExit(f"too few polygon vertex pairs: {stats['polygon_vertex_pairs']}")
if total_values < 8_000_000:
    raise SystemExit(f"too few total values: {total_values}")
if total_bytes < 32_000_000:
    raise SystemExit(f"too few primary bytes: {total_bytes}")
if total_bytes > 1_000_000_000:
    raise SystemExit(f"primary bytes exceed 1 GB cap: {total_bytes}")
if stats["samples"] != len(rows):
    raise SystemExit(f"stats/index sample mismatch: {stats['samples']} != {len(rows)}")
if stats["primary_values"] != total_values:
    raise SystemExit(f"stats/index value mismatch: {stats['primary_values']} != {total_values}")
if stats["primary_sample_bytes"] != total_bytes:
    raise SystemExit(f"stats/index byte mismatch: {stats['primary_sample_bytes']} != {total_bytes}")

print(
    f"verified dataset=google_open_buildings_v3_s2_073_geometry_f32 samples={len(rows)} "
    f"buildings={stats['buildings']} vertex_pairs={stats['polygon_vertex_pairs']} "
    f"values={total_values} bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
