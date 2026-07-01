#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_pds_sharad_radargram_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 - <<'PY' "$REPO_ROOT" "$DATA_DIR" "$DATASET_ID"
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
data_dir = sys.argv[2]
dataset_id = sys.argv[3]
data_root = repo_root / data_dir
index_path = data_root / "index" / dataset_id / "samples.jsonl"
stats_path = data_root / "filtered" / dataset_id / "ingest_stats.json"
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if not rows:
    raise SystemExit("empty sample index")
if len(rows) != int(stats["accepted_products"]):
    raise SystemExit("accepted product count mismatch")

counts = []
sizes = []
for row in rows:
    if row["dataset_id"] != dataset_id:
        raise SystemExit(f"dataset mismatch: {row['dataset_id']}")
    if row["series_id"] != "sharad_radargram_backscatter_f32" or row["role"] != "primary":
        raise SystemExit(f"unexpected series/role: {row['series_id']} {row['role']}")
    if row["numeric_kind"] != "float" or int(row["bit_width"]) != 32 or row["endianness"] != "little":
        raise SystemExit(f"unexpected numeric representation: {row}")
    if row["sample_rank"] != 2 or len(row["sample_shape"]) != 2:
        raise SystemExit(f"unexpected sample shape: {row['sample_shape']}")
    sample = data_root / row["sample_path"]
    if not sample.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    expected_size = int(row["value_count"]) * int(row["element_size_bytes"])
    actual_size = sample.stat().st_size
    if actual_size != expected_size or actual_size != int(row["sample_size_bytes"]):
        raise SystemExit(f"size mismatch: {row['sample_path']}")
    if row["min"] == row["max"]:
        raise SystemExit(f"constant sample: {row['sample_path']}")
    counts.append(int(row["value_count"]))
    sizes.append(actual_size)

if sum(counts) != int(stats["primary_values"]):
    raise SystemExit("primary value total mismatch")
if sum(sizes) != int(stats["primary_sample_bytes"]):
    raise SystemExit("primary byte total mismatch")
if sum(counts) < 10000 or sum(sizes) < 102400 or statistics.median(counts) < 1000:
    raise SystemExit("primary output below acceptance floor")

print(f"verified_samples={len(rows)} primary_values={sum(counts)} primary_sample_bytes={sum(sizes)}")
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
