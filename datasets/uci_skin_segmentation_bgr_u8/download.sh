#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_skin_segmentation_bgr_u8"
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

echo "[$(date -Is)] download start dataset=$DATASET_ID"
curl -fL --retry 3 --retry-delay 2 -o "$DOWNLOAD_DIR/skin-segmentation.zip" "https://archive.ics.uci.edu/static/public/229/skin+segmentation.zip"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import os
import zipfile
from pathlib import Path

archive = Path(os.environ["DOWNLOAD_DIR"]) / "skin-segmentation.zip"
with zipfile.ZipFile(archive) as zf:
    members = [name for name in zf.namelist() if not name.endswith("/") and name.lower().endswith((".txt", ".data", ".csv"))]
    if len(members) != 1:
        raise SystemExit(f"expected one data table member, found {members}")
    rows = 0
    with zf.open(members[0]) as raw:
        for line_number, raw_line in enumerate(raw, start=1):
            line = raw_line.decode("ascii").strip()
            if not line:
                continue
            values = [int(part) for part in line.replace(",", " ").split()]
            if len(values) != 4:
                raise SystemExit(f"line {line_number}: expected 4 columns, got {len(values)}")
            if any(value < 0 or value > 255 for value in values[:3]):
                raise SystemExit(f"line {line_number}: BGR value outside uint8 range")
            if values[3] not in {1, 2}:
                raise SystemExit(f"line {line_number}: label outside 1..2")
            rows += 1
    if rows != 245057:
        raise SystemExit(f"unexpected row count {rows}")
print("semantic_validation=ok rows=245057")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
