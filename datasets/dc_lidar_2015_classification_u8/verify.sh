#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dc_lidar_2015_classification_u8"
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

MIN_MEDIAN_VALUES = 1_000
MIN_TOTAL_VALUES = 10_000
MIN_TOTAL_BYTES = 102_400
MAX_PRIMARY_BYTES = 1_000_000_000
FAMILY = "dc_lidar_classification_code_u8"

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
primary = [r for r in rows if r.get("role", "primary") == "primary"]
if not primary:
    raise SystemExit("no primary samples")
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
for r in primary:
    if r["sample_path"] in seen_paths:
        raise SystemExit(f"duplicate sample path: {r['sample_path']}")
    seen_paths.add(r["sample_path"])
    if r["numeric_kind"] != "uint" or int(r["bit_width"]) != 8 or int(r["element_size_bytes"]) != 1:
        raise SystemExit(f"not uint8: {r['sample_path']}")
    if r.get("container_format") != "las" or r.get("natural_record_kind") != "las_tile":
        raise SystemExit(f"unexpected source semantics: {r['sample_path']}")
    point_format = int(r["point_format"])
    if not (0 <= point_format <= 10):
        raise SystemExit(f"unsupported point format in index: {point_format}")
    p = root / r["sample_path"]
    if not p.is_file():
        raise SystemExit(f"missing sample {r['sample_path']}")
    data = p.read_bytes()
    if len(data) != int(r["sample_size_bytes"]) or len(data) != int(r["value_count"]):
        raise SystemExit(f"size mismatch {r['sample_path']}")
    unique = set(data[: min(len(data), 1_000_000)])
    if len(unique) > 1:
        nonconstant += 1
    if point_format <= 5 and any(v > 31 for v in unique):
        raise SystemExit(f"old LAS classification code exceeds 31: {r['sample_path']}")
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
