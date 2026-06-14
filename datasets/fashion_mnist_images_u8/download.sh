#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="fashion_mnist_images_u8"
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
BASE_URL="https://github.com/zalandoresearch/fashion-mnist/raw/master/data/fashion"
for file in train-images-idx3-ubyte.gz train-labels-idx1-ubyte.gz t10k-images-idx3-ubyte.gz t10k-labels-idx1-ubyte.gz; do
  curl -fL --retry 3 --retry-delay 2 -o "$DOWNLOAD_DIR/$file" "$BASE_URL/$file"
done

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import gzip
import os
import struct
from pathlib import Path

download_dir = Path(os.environ["DOWNLOAD_DIR"])
expected = {
    "train-images-idx3-ubyte.gz": (2051, 60000, 28, 28),
    "t10k-images-idx3-ubyte.gz": (2051, 10000, 28, 28),
    "train-labels-idx1-ubyte.gz": (2049, 60000),
    "t10k-labels-idx1-ubyte.gz": (2049, 10000),
}

for name, spec in expected.items():
    path = download_dir / name
    with gzip.open(path, "rb") as fh:
        if spec[0] == 2051:
            header = fh.read(16)
            if len(header) != 16:
                raise SystemExit(f"{name}: truncated IDX image header")
            magic, count, rows, cols = struct.unpack(">IIII", header)
            if (magic, count, rows, cols) != spec:
                raise SystemExit(f"{name}: unexpected IDX image header {(magic, count, rows, cols)}")
        else:
            header = fh.read(8)
            if len(header) != 8:
                raise SystemExit(f"{name}: truncated IDX label header")
            magic, count = struct.unpack(">II", header)
            if (magic, count) != spec:
                raise SystemExit(f"{name}: unexpected IDX label header {(magic, count)}")
print("semantic_validation=ok")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
