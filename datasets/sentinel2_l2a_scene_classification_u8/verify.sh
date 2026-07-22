#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sentinel2_l2a_scene_classification_u8"
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
from pathlib import Path

DATASET_ID = "sentinel2_l2a_scene_classification_u8"
SERIES_ID = "sentinel2_l2a_scene_class_u8"
ALLOWED = set(range(12))

data_root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"

if not index_path.is_file():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
primary = [row for row in rows if row.get("role") == "primary"]
if len(primary) < 2:
    raise SystemExit(f"too few primary samples: {len(primary)}")

counts: list[int] = []
total_bytes = 0
seen_scene_ids: set[str] = set()
for row in primary:
    if row.get("dataset_id") != DATASET_ID:
        raise SystemExit(f"wrong dataset_id: {row.get('dataset_id')}")
    if row.get("series_id") != SERIES_ID:
        raise SystemExit(f"wrong series_id: {row.get('series_id')}")
    if row.get("numeric_kind") != "uint" or int(row.get("bit_width")) != 8:
        raise SystemExit(f"wrong numeric type: {row}")
    if row.get("source_format") != "cloud_optimized_geotiff":
        raise SystemExit(f"wrong source_format: {row.get('source_format')}")
    if row.get("source_field") != "SCL.band_1.scene_classification_code":
        raise SystemExit(f"wrong source_field: {row.get('source_field')}")
    if row.get("natural_record_kind") != "sentinel2_l2a_scl_scene_raster":
        raise SystemExit(f"wrong natural_record_kind: {row.get('natural_record_kind')}")
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {path}")
    data = path.read_bytes()
    if len(data) != int(row["sample_size_bytes"]) or len(data) != int(row["value_count"]):
        raise SystemExit(f"size mismatch: {row['sample_path']}")
    values = set(data)
    unexpected = values - ALLOWED
    if unexpected:
        raise SystemExit(f"unexpected SCL values in {row['sample_path']}: {sorted(unexpected)}")
    if len(values) <= 1:
        raise SystemExit(f"constant sample: {row['sample_path']}")
    if row["scene_id"] in seen_scene_ids:
        raise SystemExit(f"duplicate scene sample: {row['scene_id']}")
    seen_scene_ids.add(row["scene_id"])
    counts.append(len(data))
    total_bytes += len(data)

if sum(counts) < 10_000 or total_bytes < 100 * 1024:
    raise SystemExit(f"aggregate floor failed: values={sum(counts)} bytes={total_bytes}")
if statistics.median(counts) < 1_000:
    raise SystemExit(f"median sample below floor: {statistics.median(counts)}")
if total_bytes > 1_000_000_000:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if int(stats["samples"]) != len(primary):
    raise SystemExit(f"stats/index sample mismatch: {stats['samples']} != {len(primary)}")
if int(stats["primary_values"]) != sum(counts):
    raise SystemExit(f"stats/index value mismatch: {stats['primary_values']} != {sum(counts)}")
if int(stats["primary_sample_bytes"]) != total_bytes:
    raise SystemExit(f"stats/index byte mismatch: {stats['primary_sample_bytes']} != {total_bytes}")

print(
    f"verified dataset={DATASET_ID} samples={len(primary)} "
    f"values={sum(counts)} bytes={total_bytes} median={int(statistics.median(counts))}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
