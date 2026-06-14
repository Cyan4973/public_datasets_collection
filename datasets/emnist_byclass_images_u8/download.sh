#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="emnist_byclass_images_u8"
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
curl -fL --retry 3 --retry-delay 2 -o "$DOWNLOAD_DIR/gzip.zip" "https://biometrics.nist.gov/cs_links/EMNIST/gzip.zip"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import gzip
import os
import struct
import zipfile
from pathlib import Path

archive = Path(os.environ["DOWNLOAD_DIR"]) / "gzip.zip"
members = {
    "gzip/emnist-byclass-train-images-idx3-ubyte.gz": (2051, 697932, 28, 28),
    "gzip/emnist-byclass-test-images-idx3-ubyte.gz": (2051, 116323, 28, 28),
    "gzip/emnist-byclass-train-labels-idx1-ubyte.gz": (2049, 697932),
    "gzip/emnist-byclass-test-labels-idx1-ubyte.gz": (2049, 116323),
}
with zipfile.ZipFile(archive) as zf:
    names = set(zf.namelist())
    missing = sorted(set(members) - names)
    if missing:
        raise SystemExit(f"missing archive members: {missing}")
    for name, spec in members.items():
        with zf.open(name) as raw, gzip.GzipFile(fileobj=raw) as fh:
            if spec[0] == 2051:
                header = fh.read(16)
                if len(header) != 16:
                    raise SystemExit(f"{name}: truncated IDX image header")
                got = struct.unpack(">IIII", header)
            else:
                header = fh.read(8)
                if len(header) != 8:
                    raise SystemExit(f"{name}: truncated IDX label header")
                got = struct.unpack(">II", header)
            if got != spec:
                raise SystemExit(f"{name}: unexpected IDX header {got}")
print("semantic_validation=ok")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
