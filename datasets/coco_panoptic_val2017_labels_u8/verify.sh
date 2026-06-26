#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="coco_panoptic_val2017_labels_u8"
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

MIN_SAMPLES_PER_FAMILY = 25
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
CAT_FAMILY = "coco_panoptic_category_id_u8"
SEG_FAMILY = "coco_panoptic_segment_id_u32"

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
primary = [r for r in rows if r.get("role", "primary") == "primary"]
if not primary:
    raise SystemExit("no primary samples")

by_family: dict[str, list[dict[str, object]]] = defaultdict(list)
for r in primary:
    by_family[str(r["series_id"])].append(r)
if CAT_FAMILY not in by_family:
    raise SystemExit(f"missing required family {CAT_FAMILY}")
if set(by_family) - {CAT_FAMILY, SEG_FAMILY}:
    raise SystemExit(f"unexpected families: {sorted(by_family)}")

for fam, samples in by_family.items():
    if len(samples) < MIN_SAMPLES_PER_FAMILY:
        raise SystemExit(f"family {fam} has {len(samples)} samples < {MIN_SAMPLES_PER_FAMILY}")
    expected = ("uint", 8, 1) if fam == CAT_FAMILY else ("uint", 32, 4)
    for s in samples:
        got = (s["numeric_kind"], int(s["bit_width"]), int(s["element_size_bytes"]))
        if got != expected:
            raise SystemExit(f"bad numeric declaration for {s['sample_path']}: {got} != {expected}")

if SEG_FAMILY in by_family:
    cat_ids = {int(s["image_id"]) for s in by_family[CAT_FAMILY]}
    seg_ids = {int(s["image_id"]) for s in by_family[SEG_FAMILY]}
    if cat_ids != seg_ids:
        raise SystemExit("category and segment-id family image sets differ")

total_bytes = sum(int(r["sample_size_bytes"]) for r in primary)
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")

counts = [int(r["value_count"]) for r in primary]
median_values = statistics.median(counts)
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")

checked = 0
nonconstant = 0
for r in sorted(primary, key=lambda x: x["sample_path"]):
    p = root / str(r["sample_path"])
    if not p.is_file():
        raise SystemExit(f"missing sample {r['sample_path']}")
    size = p.stat().st_size
    elem = int(r["element_size_bytes"])
    if size != int(r["sample_size_bytes"]):
        raise SystemExit(f"size mismatch {r['sample_path']}")
    if size != int(r["value_count"]) * elem:
        raise SystemExit(f"value count / element size mismatch {r['sample_path']}")
    if checked < 200:
        data = p.read_bytes()
        if elem == 1:
            if len(set(data)) > 1:
                nonconstant += 1
        else:
            vals = {struct.unpack_from("<I", data, off)[0] for off in range(0, min(len(data), 65536), 4)}
            if len(vals) > 1:
                nonconstant += 1
        checked += 1
if nonconstant == 0:
    raise SystemExit("all checked samples are constant")

fam_counts = {f: len(s) for f, s in sorted(by_family.items())}
print(
    f"verified families={fam_counts} samples={len(primary)} "
    f"median_values={int(median_values)} total_values={sum(counts)} total_bytes={total_bytes} "
    f"nonconstant_checked={nonconstant}/{checked}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
