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
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] local import start dataset=$DATASET_ID"
DEFAULT_ROWS_DIR="/home/cyan/dev/openzl/training_data/numeric_datasets/16bit/datasets/srtm_skadi_elevation"
ROWS_SOURCE="${LOCAL_ROWS_DIR:-$DEFAULT_ROWS_DIR}"
ROWS_TARGET="$DOWNLOAD_DIR/row_shards"
HGT_TARGET="$DOWNLOAD_DIR/N37W122.hgt.gz"

if [[ -n "${LOCAL_HGT_GZ:-}" ]]; then
  cp "$LOCAL_HGT_GZ" "$HGT_TARGET"
elif [[ -d "$ROWS_SOURCE" ]]; then
  rm -rf "$ROWS_TARGET"
  mkdir -p "$ROWS_TARGET"
  cp "$ROWS_SOURCE"/N37W122_rows_*.bin "$ROWS_TARGET"/
else
  cat >&2 <<EOF
No local Skadi source found.

Provide one of:
  LOCAL_ROWS_DIR=/path/to/srtm_skadi_elevation $0
  LOCAL_HGT_GZ=/path/to/N37W122.hgt.gz $0

This recipe intentionally does not download additional Skadi tiles.
EOF
  exit 1
fi

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
import re
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
rows_dir = download_dir / "row_shards"
hgt_path = download_dir / "N37W122.hgt.gz"
tile_values = 3601 * 3601
tile_bytes = tile_values * 2

records = []
if hgt_path.exists():
    raw = gzip.decompress(hgt_path.read_bytes())
    if len(raw) != tile_bytes:
        raise SystemExit(f"unexpected decoded HGT size: {len(raw)}")
    records.append({"source": hgt_path.name, "source_bytes": hgt_path.stat().st_size, "decoded_bytes": len(raw), "source_kind": "hgt_gzip"})
elif rows_dir.exists():
    pattern = re.compile(r"^N37W122_rows_(\d{4})_(\d{4})\.bin$")
    covered: list[tuple[int, int]] = []
    files = sorted(rows_dir.glob("N37W122_rows_*.bin"))
    if not files:
        raise SystemExit(f"missing row shard files in {rows_dir}")
    for path in files:
        match = pattern.match(path.name)
        if not match:
            raise SystemExit(f"unexpected row shard name: {path.name}")
        start = int(match.group(1))
        end = int(match.group(2))
        if start > end:
            raise SystemExit(f"invalid row range: {path.name}")
        expected_bytes = (end - start + 1) * 3601 * 2
        actual_bytes = path.stat().st_size
        if actual_bytes != expected_bytes:
            raise SystemExit(f"row shard size mismatch: {path.name} expected {expected_bytes} got {actual_bytes}")
        covered.append((start, end))
        records.append({"source": path.name, "source_bytes": actual_bytes, "row_start": start, "row_end": end, "source_kind": "row_shard"})
    expected_start = 0
    for start, end in sorted(covered):
        if start != expected_start:
            raise SystemExit(f"row coverage gap or overlap before row {start}; expected {expected_start}")
        expected_start = end + 1
    if expected_start != 3601:
        raise SystemExit(f"row coverage ended at {expected_start - 1}, expected 3600")
else:
    raise SystemExit("missing local HGT gzip or row shard import")

inventory = {
    "dataset_id": "skadi_srtm_bay_area_hgt_i16",
    "tile": "N37W122",
    "records": records,
    "record_count": len(records),
    "source_bytes": sum(row["source_bytes"] for row in records),
}
(download_dir / "local_import_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"semantic_validation=ok source_records={len(records)} source_bytes={inventory['source_bytes']}")
PY

echo "[$(date -Is)] local import done dataset=$DATASET_ID"
