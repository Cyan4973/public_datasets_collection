#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_letter_recognition_u8"
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
curl -fL --retry 3 --retry-delay 2 -o "$DOWNLOAD_DIR/letter-recognition.zip" "https://archive.ics.uci.edu/static/public/59/letter+recognition.zip"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import os
import zipfile
from pathlib import Path

archive = Path(os.environ["DOWNLOAD_DIR"]) / "letter-recognition.zip"
with zipfile.ZipFile(archive) as zf:
    if "letter-recognition.data" not in zf.namelist():
        raise SystemExit("missing letter-recognition.data")
    with zf.open("letter-recognition.data") as raw:
        rows = 0
        for row in csv.reader(line.decode("ascii") for line in raw):
            rows += 1
            if len(row) != 17:
                raise SystemExit(f"row {rows}: expected 17 columns, got {len(row)}")
            if len(row[0]) != 1 or not ("A" <= row[0] <= "Z"):
                raise SystemExit(f"row {rows}: invalid label {row[0]!r}")
            for value in row[1:]:
                ivalue = int(value)
                if ivalue < 0 or ivalue > 15:
                    raise SystemExit(f"row {rows}: feature out of range {ivalue}")
        if rows != 20000:
            raise SystemExit(f"unexpected row count {rows}")
print("semantic_validation=ok rows=20000")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
