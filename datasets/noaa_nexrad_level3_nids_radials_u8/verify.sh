#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_nexrad_level3_nids_radials_u8"
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

DATASET_ID = "noaa_nexrad_level3_nids_radials_u8"
SERIES_ID = "nexrad_l3_packet16_radial_bins_u8"
MIN_SAMPLES = 24
MIN_MEDIAN_VALUES = 1_000
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
primary = [row for row in rows if row.get("role") == "primary"]
if len(primary) < MIN_SAMPLES:
    raise SystemExit(f"too few primary samples: {len(primary)} < {MIN_SAMPLES}")
if {row["dataset_id"] for row in primary} != {DATASET_ID}:
    raise SystemExit("unexpected dataset IDs")
if {row["series_id"] for row in primary} != {SERIES_ID}:
    raise SystemExit("unexpected series IDs")
if len({row["product_code"] for row in primary}) != 1:
    raise SystemExit("mixed product codes")
if {int(row["packet_code"]) for row in primary} != {16}:
    raise SystemExit("non-packet-16 sample present")

seen_paths: set[str] = set()
counts: list[int] = []
shapes: set[tuple[int, int]] = set()
for row in primary:
    sample_path = row["sample_path"]
    if sample_path in seen_paths:
        raise SystemExit(f"duplicate sample path: {sample_path}")
    seen_paths.add(sample_path)
    if row["numeric_kind"] != "uint" or int(row["bit_width"]) != 8 or int(row["element_size_bytes"]) != 1:
        raise SystemExit(f"not uint8: {sample_path}")
    if row.get("natural_record_kind") != "nexrad_level3_packet16_product":
        raise SystemExit(f"bad natural record kind: {sample_path}")
    shape = tuple(int(v) for v in row["sample_shape"])
    if len(shape) != 2 or shape[0] <= 0 or shape[1] <= 0:
        raise SystemExit(f"bad sample shape: {sample_path}")
    shapes.add(shape)
    expected_values = shape[0] * shape[1]
    if expected_values != int(row["value_count"]):
        raise SystemExit(f"shape/value mismatch: {sample_path}")
    path = root / sample_path
    if not path.is_file():
        raise SystemExit(f"missing sample: {sample_path}")
    data = path.read_bytes()
    if len(data) != int(row["sample_size_bytes"]) or len(data) != int(row["value_count"]):
        raise SystemExit(f"size mismatch: {sample_path}")
    if len(set(data[: min(len(data), 65536)])) <= 1:
        raise SystemExit(f"constant decoded bin prefix: {sample_path}")
    counts.append(len(data))

primary_bytes = sum(counts)
median_values = statistics.median(counts)
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")
if int(stats["primary_sample_bytes"]) != primary_bytes or int(stats["primary_values"]) != primary_bytes:
    raise SystemExit("stats/index primary byte mismatch")
if int(stats["samples"]) != len(primary):
    raise SystemExit("stats/index sample count mismatch")

print(
    f"verified dataset={DATASET_ID} product={primary[0]['product_code']} "
    f"samples={len(primary)} shapes={sorted(shapes)} total_values={primary_bytes}"
)
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
