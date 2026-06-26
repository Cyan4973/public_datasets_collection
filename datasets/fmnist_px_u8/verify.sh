#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="fmnist_px_u8"
FAMILY="fmnist_pixel_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR FAMILY
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from pathlib import Path

MIN_SAMPLES = 5
MIN_MEDIAN_VALUES = 1_000
MAX_FAMILY_BYTES = 1_000_000_000
FAMILY = os.environ["FAMILY"]
ALLOWED = {FAMILY}

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
primary = [r for r in rows if r.get("role", "primary") == "primary"]

by_family = defaultdict(list)
for r in primary:
    by_family[r["series_id"]].append(r)

if set(by_family) != ALLOWED:
    raise SystemExit(f"unexpected families: {sorted(by_family)}")
for fam, samples in by_family.items():
    if len(samples) < MIN_SAMPLES:
        raise SystemExit(f"family {fam} has {len(samples)} samples < {MIN_SAMPLES}")
    if sum(int(s["sample_size_bytes"]) for s in samples) > MAX_FAMILY_BYTES:
        raise SystemExit(f"family {fam} bytes exceed cap")
    if {(s["numeric_kind"], s["bit_width"]) for s in samples} != {("uint", 8)}:
        raise SystemExit(f"family {fam} is not uint8")

counts = [int(r["value_count"]) for r in primary]
median_values = statistics.median(counts)
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")

for r in primary:
    p = root / r["sample_path"]
    if not p.is_file():
        raise SystemExit(f"missing sample {r['sample_path']}")
    if p.stat().st_size != int(r["sample_size_bytes"]):
        raise SystemExit(f"size mismatch {r['sample_path']}")
    if int(r["sample_size_bytes"]) != int(r["value_count"]):
        raise SystemExit(f"bad u8 sizing {r['sample_path']}")
    if len(set(p.read_bytes()[:65536])) <= 1:
        raise SystemExit(f"constant primary sample rejected: {r['sample_path']}")

print(f"verified family={FAMILY} samples={len(primary)} "
      f"median_values={int(median_values)} total_values={sum(counts)}")
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
