#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_nexrad_level3_products_u8"
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

MIN_SAMPLES = 5
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
FAMILY = "nexrad_level3_nids_payload_u8"

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
product_codes = {r.get("product_code") for r in primary}
if len(product_codes) != 1:
    raise SystemExit(f"mixed product codes: {sorted(product_codes)}")

counts = [int(r["value_count"]) for r in primary]
total_bytes = sum(int(r["sample_size_bytes"]) for r in primary)
median_values = statistics.median(counts)
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")

nonconstant = 0
seen_paths: set[str] = set()
for r in primary:
    if r["sample_path"] in seen_paths:
        raise SystemExit(f"duplicate sample path: {r['sample_path']}")
    seen_paths.add(r["sample_path"])
    if r["numeric_kind"] != "uint" or int(r["bit_width"]) != 8 or int(r["element_size_bytes"]) != 1:
        raise SystemExit(f"not uint8: {r['sample_path']}")
    p = root / r["sample_path"]
    if not p.is_file():
        raise SystemExit(f"missing sample {r['sample_path']}")
    data = p.read_bytes()
    if len(data) != int(r["sample_size_bytes"]) or len(data) != int(r["value_count"]):
        raise SystemExit(f"size mismatch {r['sample_path']}")
    if len(set(data[: min(len(data), 65536)])) > 1:
        nonconstant += 1
if nonconstant != len(primary):
    raise SystemExit(f"constant primary samples found: nonconstant={nonconstant} total={len(primary)}")

print(
    f"verified family={FAMILY} product={next(iter(product_codes))} samples={len(primary)} "
    f"median_values={int(median_values)} total_values={sum(counts)} total_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
