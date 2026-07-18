#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_quickdraw_bitmap_classes_u8"
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

rows = []
total_bytes = 0
total_values = 0
for line in index_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("dataset_id") != "google_quickdraw_bitmap_classes_u8":
        raise SystemExit(f"wrong dataset_id: {row.get('dataset_id')}")
    if row.get("family") != "quickdraw_bitmap_28x28_u8":
        raise SystemExit(f"wrong family: {row.get('family')}")
    if row.get("numeric_kind") != "uint" or row.get("bit_width") != 8:
        raise SystemExit(f"unexpected numeric representation: {row}")
    if row.get("sample_rank") != 3 or row.get("sample_shape", [None, None, None])[1:] != [28, 28]:
        raise SystemExit(f"unexpected sample geometry: {row}")
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {path}")
    size = path.stat().st_size
    if size != row["sample_size_bytes"]:
        raise SystemExit(f"size mismatch for {path}: {size} != {row['sample_size_bytes']}")
    if size != row["value_count"]:
        raise SystemExit(f"value count mismatch for {path}")
    if size != row["sample_shape"][0] * 28 * 28:
        raise SystemExit(f"shape/size mismatch for {path}")
    total_bytes += size
    total_values += int(row["value_count"])
    rows.append(row)

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if len(rows) < 4:
    raise SystemExit(f"too few samples: {len(rows)}")
if total_values < 400_000_000:
    raise SystemExit(f"too few total values: {total_values}")
if total_bytes < 400_000_000:
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
    f"verified dataset=google_quickdraw_bitmap_classes_u8 samples={len(rows)} "
    f"values={total_values} bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
