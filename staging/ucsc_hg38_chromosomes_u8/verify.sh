#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ucsc_hg38_chromosomes_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

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

DATASET_ID = "ucsc_hg38_chromosomes_u8"
SERIES_ID = "hg38_primary_chromosome_bases"
ALLOWED = set(b"ACGTRYSWKMBDHVNacgtryswkmbdhvn")
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != 25:
    raise SystemExit(f"expected 25 chromosome samples, found {len(rows)}")
sizes = []
for row in rows:
    if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID or row["numeric_kind"] != "uint" or row["bit_width"] != 8:
        raise SystemExit(f"unexpected row: {row}")
    path = data_root / row["sample_path"]
    payload = path.read_bytes()
    if len(payload) != row["sample_size_bytes"] or len(payload) != row["value_count"]:
        raise SystemExit(f"size/count mismatch: {path}")
    if len(payload) < 1000:
        raise SystemExit(f"natural chromosome sample below floor: {path}")
    bad = set(payload) - ALLOWED
    if bad:
        raise SystemExit(f"unexpected sequence byte(s) in {path}: {sorted(bad)}")
    if len(set(payload)) < 2:
        raise SystemExit(f"degenerate chromosome sample: {path}")
    sizes.append(len(payload))
if len(set(sizes)) < 2:
    raise SystemExit("all chromosome samples have identical size")
if sum(sizes) < 10000 or sum(sizes) < 100 * 1024:
    raise SystemExit("primary payload below aggregate floor")
if statistics.median(sizes) < 1000:
    raise SystemExit("primary median sample size below floor")
print(f"verified_rows={len(rows)} primary_samples={len(rows)} primary_values={sum(sizes)} primary_bytes={sum(sizes)} size_range={min(sizes)}/{int(statistics.median(sizes))}/{max(sizes)}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
