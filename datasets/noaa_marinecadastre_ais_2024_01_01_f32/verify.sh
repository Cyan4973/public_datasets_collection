#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_marinecadastre_ais_2024_01_01_f32"
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

DATASET_ID = "noaa_marinecadastre_ais_2024_01_01_f32"
MIN_SAMPLES = 8
MIN_PRIMARY_VALUES = 8_000_000
MIN_PRIMARY_BYTES = 32_000_000
MIN_MEDIAN_VALUES = 500_000
MAX_PRIMARY_BYTES = 1_000_000_000
REQUIRED_FIELDS = {"LAT", "LON", "SOG", "COG", "HEADING"}

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
    if row.get("sample_geometry") != "table_column" or row.get("natural_record_kind") != "noaa_marinecadastre_ais_numeric_field":
        raise SystemExit(f"unexpected sample metadata: {row}")
    path = root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    data = path.read_bytes()
    count = int(row["value_count"])
    if len(data) != count * 4 or len(data) != int(row["sample_size_bytes"]):
        raise SystemExit(f"size mismatch: {row['sample_path']}")
    prefix_count = min(count, 200_000)
    prefix = struct.unpack("<" + "f" * prefix_count, data[: prefix_count * 4])
    if any(not math.isfinite(value) for value in prefix):
        raise SystemExit(f"non-finite prefix values: {row['sample_path']}")
    if len(set(prefix)) <= 1:
        raise SystemExit(f"constant prefix: {row['sample_path']}")
    if float(row["max"]) <= float(row["min"]):
        raise SystemExit(f"bad min/max metadata: {row['sample_path']}")
    counts.append(count)
    sizes.append(len(data))
    fields.add(row["source_field"])

missing = sorted(REQUIRED_FIELDS - fields)
if missing:
    raise SystemExit(f"missing required AIS movement fields: {missing}")
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

print(
    f"verified dataset={DATASET_ID} samples={len(primary)} fields={len(fields)} "
    f"median_values={int(median_values)} total_values={total_values} total_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
