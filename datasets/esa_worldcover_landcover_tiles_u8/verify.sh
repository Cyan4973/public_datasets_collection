#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="esa_worldcover_landcover_tiles_u8"
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

MIN_SAMPLES = 12
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
FAMILY = "worldcover_landcover_class_u8"
ALLOWED_VALUES = {0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
primary = [r for r in rows if r.get("role", "primary") == "primary"]
if len(primary) < MIN_SAMPLES:
    raise SystemExit(f"only {len(primary)} primary samples < {MIN_SAMPLES}")
if {r["series_id"] for r in primary} != {FAMILY}:
    raise SystemExit(f"unexpected families: {sorted({r['series_id'] for r in primary})}")

counts = [int(r["value_count"]) for r in primary]
total_bytes = sum(int(r["sample_size_bytes"]) for r in primary)
median_values = statistics.median(counts)
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")

nonconstant = 0
for r in primary:
    if r["numeric_kind"] != "uint" or int(r["bit_width"]) != 8 or int(r["element_size_bytes"]) != 1:
        raise SystemExit(f"not uint8: {r['sample_path']}")
    p = root / r["sample_path"]
    if not p.is_file():
        raise SystemExit(f"missing sample {r['sample_path']}")
    data = p.read_bytes()
    if len(data) != int(r["sample_size_bytes"]) or len(data) != int(r["value_count"]):
        raise SystemExit(f"size mismatch {r['sample_path']}")
    unknown = set(data) - ALLOWED_VALUES
    if unknown:
        raise SystemExit(f"unexpected class codes in {r['sample_path']}: {sorted(unknown)[:10]}")
    if len(set(data)) > 1:
        nonconstant += 1
if nonconstant != len(primary):
    raise SystemExit(f"constant primary samples found: nonconstant={nonconstant} total={len(primary)}")

print(
    f"verified family={FAMILY} samples={len(primary)} median_values={int(median_values)} "
    f"total_values={sum(counts)} total_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
