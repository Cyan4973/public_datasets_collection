#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usda_fia_ca_tree_measurements_f32"
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

DATASET_ID = "usda_fia_ca_tree_measurements_f32"
MIN_SAMPLES = 20
MIN_PRIMARY_VALUES = 1_000_000
MIN_PRIMARY_BYTES = 4_000_000
MIN_MEDIAN_VALUES = 50_000
MAX_PRIMARY_BYTES = 1_000_000_000

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing stats: {stats_path}")
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
primary = [row for row in rows if row.get("role", "primary") == "primary"]
if len(primary) < MIN_SAMPLES:
    raise SystemExit(f"too few primary samples: {len(primary)}")

counts = []
sizes = []
fields = set()
for row in primary:
    if row["dataset_id"] != DATASET_ID:
        raise SystemExit(f"unexpected dataset row: {row}")
    if row["numeric_kind"] != "float" or int(row["bit_width"]) != 32 or int(row["element_size_bytes"]) != 4:
        raise SystemExit(f"not float32: {row['sample_path']}")
    if row.get("sample_geometry") != "table_column" or row.get("natural_record_kind") != "usda_fia_tree_measurement_column":
        raise SystemExit(f"unexpected sample metadata: {row}")
    if row.get("source_state") != "CA" or row.get("source_table") != "TREE":
        raise SystemExit(f"unexpected source table metadata: {row}")
    path = root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    data = path.read_bytes()
    count = int(row["value_count"])
    if len(data) != count * 4 or len(data) != int(row["sample_size_bytes"]):
        raise SystemExit(f"size mismatch: {row['sample_path']}")
    values = struct.unpack("<" + "f" * count, data)
    if any(not math.isfinite(value) for value in values):
        raise SystemExit(f"non-finite sample values: {row['sample_path']}")
    if len(set(values)) <= 1:
        raise SystemExit(f"constant sample: {row['sample_path']}")
    if abs(min(values) - float(row["min"])) > 1e-6 or abs(max(values) - float(row["max"])) > 1e-6:
        raise SystemExit(f"min/max metadata mismatch: {row['sample_path']}")
    counts.append(count)
    sizes.append(len(data))
    fields.add(row["source_field"])

total_values = sum(counts)
total_bytes = sum(sizes)
median_values = statistics.median(counts)
if total_values < MIN_PRIMARY_VALUES or total_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"aggregate floor not met: values={total_values} bytes={total_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample below floor: {median_values}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")
if int(stats["primary_sample_bytes"]) != total_bytes:
    raise SystemExit("stats/index byte mismatch")
if int(stats["primary_values"]) != total_values:
    raise SystemExit("stats/index value mismatch")
if len(fields) != len(primary):
    raise SystemExit(f"field/sample mismatch: fields={len(fields)} samples={len(primary)}")

print(
    f"verified dataset={DATASET_ID} samples={len(primary)} fields={len(fields)} "
    f"median_values={int(median_values)} total_values={total_values} total_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
