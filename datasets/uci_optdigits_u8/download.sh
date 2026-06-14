#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_optdigits_u8"
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
curl -fL --retry 3 --retry-delay 2 -o "$DOWNLOAD_DIR/optdigits.zip" "https://archive.ics.uci.edu/static/public/80/optical+recognition+of+handwritten+digits.zip"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import os
import zipfile
from pathlib import Path

archive = Path(os.environ["DOWNLOAD_DIR"]) / "optdigits.zip"
expected_rows = {"optdigits.tra": 3823, "optdigits.tes": 1797}
with zipfile.ZipFile(archive) as zf:
    base_to_name = {Path(name).name: name for name in zf.namelist() if not name.endswith("/")}
    missing = sorted(set(expected_rows) - set(base_to_name))
    if missing:
        raise SystemExit(f"missing data members: {missing}")
    for base, expected in expected_rows.items():
        rows = 0
        with zf.open(base_to_name[base]) as raw:
            for line_number, raw_line in enumerate(raw, start=1):
                line = raw_line.decode("ascii").strip()
                if not line:
                    continue
                values = [int(part) for part in line.split(",")]
                if len(values) != 65:
                    raise SystemExit(f"{base}:{line_number}: expected 65 columns, got {len(values)}")
                if any(value < 0 or value > 16 for value in values[:64]):
                    raise SystemExit(f"{base}:{line_number}: feature outside 0..16")
                if values[64] < 0 or values[64] > 9:
                    raise SystemExit(f"{base}:{line_number}: label outside 0..9")
                rows += 1
        if rows != expected:
            raise SystemExit(f"{base}: unexpected row count {rows}")
print("semantic_validation=ok rows=5620")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
