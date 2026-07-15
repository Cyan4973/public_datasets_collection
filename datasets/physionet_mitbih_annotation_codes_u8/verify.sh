#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="physionet_mitbih_annotation_codes_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
from pathlib import Path

SERIES_ID = "mitbih_wfdb_annotation_type_u8"
MIN_TOTAL_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
primary = [r for r in rows if r.get("role", "primary") == "primary"]
if not primary:
    raise SystemExit("no primary samples")
if {r["series_id"] for r in primary} != {SERIES_ID}:
    raise SystemExit(f"unexpected series: {sorted({r['series_id'] for r in primary})}")

counts: list[int] = []
total_bytes = 0
for row in primary:
    if row["numeric_kind"] != "uint" or int(row["bit_width"]) != 8 or int(row["element_size_bytes"]) != 1:
        raise SystemExit(f"not uint8: {row['sample_path']}")
    path = root / row["sample_path"]
    data = path.read_bytes()
    if len(data) != int(row["sample_size_bytes"]) or len(data) != int(row["value_count"]):
        raise SystemExit(f"size mismatch: {row['sample_path']}")
    if len(set(data)) <= 1:
        raise SystemExit(f"constant sample: {row['sample_path']}")
    bad = [v for v in set(data) if not (1 <= v <= 49)]
    if bad:
        raise SystemExit(f"unexpected WFDB annotation codes in {row['sample_path']}: {bad[:10]}")
    counts.append(len(data))
    total_bytes += len(data)

median_values = statistics.median(counts)
if sum(counts) < MIN_TOTAL_VALUES and total_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"aggregate floor failed: values={sum(counts)} bytes={total_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median values below floor: {median_values}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")
print(
    f"verified series={SERIES_ID} samples={len(primary)} "
    f"median_values={int(median_values)} total_values={sum(counts)} total_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
