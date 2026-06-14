#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="medmnist_pathmnist_images_u8"
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
curl -fL --retry 3 --retry-delay 2 -o "$DOWNLOAD_DIR/pathmnist.npz" "https://zenodo.org/records/10519652/files/pathmnist.npz?download=1"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import ast
import os
import struct
import zipfile
from pathlib import Path

archive = Path(os.environ["DOWNLOAD_DIR"]) / "pathmnist.npz"
expected = {
    "train_images.npy": (89996, 28, 28, 3),
    "val_images.npy": (10004, 28, 28, 3),
    "test_images.npy": (7180, 28, 28, 3),
}

def read_npy_header(fh):
    if fh.read(6) != b"\x93NUMPY":
        raise SystemExit("bad NPY magic")
    version = tuple(fh.read(2))
    if version == (1, 0):
        header_len = struct.unpack("<H", fh.read(2))[0]
    elif version in {(2, 0), (3, 0)}:
        header_len = struct.unpack("<I", fh.read(4))[0]
    else:
        raise SystemExit(f"unsupported NPY version {version}")
    return ast.literal_eval(fh.read(header_len).decode("latin1"))

with zipfile.ZipFile(archive) as zf:
    missing = sorted(set(expected) - set(zf.namelist()))
    if missing:
        raise SystemExit(f"missing NPZ members: {missing}")
    for name, shape in expected.items():
        with zf.open(name) as fh:
            header = read_npy_header(fh)
        if header.get("descr") != "|u1" or header.get("fortran_order") is not False or tuple(header.get("shape", ())) != shape:
            raise SystemExit(f"{name}: unexpected NPY header {header}")
print("semantic_validation=ok")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
