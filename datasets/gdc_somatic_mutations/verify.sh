#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gdc_somatic_mutations"
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
import struct
from collections import defaultdict
from pathlib import Path

MIN_FAMILIES = 1
MIN_SAMPLES_PER_FAMILY = 5
MIN_MEDIAN_VALUES = 1_000
MAX_FAMILY_BYTES = 1_000_000_000
EXPECTED_PRIMARY = {"gdc_ssm_position_u32"}

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
primary = [r for r in rows if r.get("role", "primary") == "primary"]

by_family = defaultdict(list)
for r in primary:
    by_family[r["series_id"]].append(r)

if set(by_family) != EXPECTED_PRIMARY:
    raise SystemExit(f"unexpected families: {sorted(by_family)}")
if len(by_family) < MIN_FAMILIES:
    raise SystemExit(f"only {len(by_family)} families < {MIN_FAMILIES}")

for fam, samples in by_family.items():
    if len(samples) < MIN_SAMPLES_PER_FAMILY:
        raise SystemExit(f"family {fam} has {len(samples)} samples < {MIN_SAMPLES_PER_FAMILY}")
    if sum(int(s["sample_size_bytes"]) for s in samples) > MAX_FAMILY_BYTES:
        raise SystemExit(f"family {fam} bytes exceed cap")
    if len({(s["numeric_kind"], s["bit_width"]) for s in samples}) != 1:
        raise SystemExit(f"family {fam} mixes numeric kinds/widths")

counts = [int(r["value_count"]) for r in primary]
median_values = statistics.median(counts)
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")


def unpack(path: Path, numeric_kind: str, bit_width: int, count: int) -> tuple:
    code = {("uint", 32): "I"}[(numeric_kind, bit_width)]
    data = path.read_bytes()
    if len(data) != count * (bit_width // 8):
        raise SystemExit(f"size mismatch for {path}")
    return struct.unpack("<" + code * count, data)


for r in primary:
    p = root / r["sample_path"]
    if not p.is_file():
        raise SystemExit(f"missing sample {r['sample_path']}")
    if p.stat().st_size != int(r["sample_size_bytes"]):
        raise SystemExit(f"size mismatch {r['sample_path']}")
    if len(set(unpack(p, r["numeric_kind"], int(r["bit_width"]), int(r["value_count"])))) <= 1:
        raise SystemExit(f"constant primary sample rejected: {r['sample_path']}")

fam_counts = {f: len(s) for f, s in sorted(by_family.items())}
print(f"verified families={fam_counts} samples={len(primary)} median_values={int(median_values)} total_values={sum(counts)}")
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
