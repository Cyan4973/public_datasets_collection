#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="geofabrik_liechtenstein_osm_pbf_u8"
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

DATASET_ID = "geofabrik_liechtenstein_osm_pbf_u8"
SERIES_ID = "osm_pbf_primitive_blocks"
MAX_PRIMARY_BYTES = 1_000_000_000
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) < 2:
    raise SystemExit(f"expected at least 2 primitive-block samples, found {len(rows)}")
sizes = []
for row in rows:
    if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID or row["numeric_kind"] != "uint" or row["bit_width"] != 8:
        raise SystemExit(f"unexpected row: {row}")
    path = data_root / row["sample_path"]
    payload = path.read_bytes()
    if len(payload) != row["sample_size_bytes"] or len(payload) != row["value_count"]:
        raise SystemExit(f"size/count mismatch: {path}")
    if len(set(payload)) < 2:
        raise SystemExit(f"degenerate primitive block: {path}")
    sizes.append(len(payload))
if len(set(sizes)) < 2:
    raise SystemExit("all primitive-block samples have identical size")
if sum(sizes) < 10000 or sum(sizes) < 100 * 1024:
    raise SystemExit("primary payload below aggregate floor")
if sum(sizes) > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary payload exceeds 1 GB cap: {sum(sizes)}")
if statistics.median(sizes) < 1000:
    raise SystemExit("primary median sample size below floor")
print(f"verified_rows={len(rows)} primary_samples={len(rows)} primary_values={sum(sizes)} primary_bytes={sum(sizes)} size_range={min(sizes)}/{int(statistics.median(sizes))}/{max(sizes)}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
