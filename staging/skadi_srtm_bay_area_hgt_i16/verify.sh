#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="skadi_srtm_bay_area_hgt_i16"
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
export REPO_ROOT DATA_DIR INDEX_DIR FILTER_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

DATASET_ID = "skadi_srtm_bay_area_hgt_i16"
SERIES_ID = "skadi_srtm_n37w122_elevation_i16"
TILE = "N37W122"
TILE_VALUES = 3601 * 3601
TILE_BYTES = TILE_VALUES * 2

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != 1:
    raise SystemExit(f"expected one whole-tile sample, got {len(rows)}")
row = rows[0]
if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID or row.get("tile") != TILE:
    raise SystemExit(f"unexpected row identity: {row}")
if row["numeric_kind"] != "int" or int(row["bit_width"]) != 16 or row["endianness"] != "little":
    raise SystemExit(f"unexpected numeric representation: {row}")
if int(row["value_count"]) != TILE_VALUES:
    raise SystemExit(f"unexpected value count: {row['value_count']}")
sample_path = data_root / row["sample_path"]
if not sample_path.is_file():
    raise SystemExit(f"missing sample file: {sample_path}")
actual = sample_path.stat().st_size
declared = int(row["sample_size_bytes"])
if actual != declared or declared != TILE_BYTES:
    raise SystemExit(f"size mismatch: {sample_path}")
with sample_path.open("rb") as fh:
    prefix = fh.read(20000)
if len(set(prefix)) < 2:
    raise SystemExit("degenerate tile prefix")
print(
    "verified_rows=1 "
    f"primary_samples=1 primary_values={TILE_VALUES} primary_bytes={TILE_BYTES} "
    f"size_range={TILE_BYTES}/{TILE_BYTES}/{TILE_BYTES} source_kind={row.get('source_kind', '')}"
)
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
