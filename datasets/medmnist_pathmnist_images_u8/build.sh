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
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import struct
import zipfile
from functools import reduce
from operator import mul
from pathlib import Path

DATASET_ID = "medmnist_pathmnist_images_u8"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive = download_dir / "pathmnist.npz"

def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

def read_npy_header(fh) -> dict:
    if fh.read(6) != b"\x93NUMPY":
        raise RuntimeError("bad NPY magic")
    version = tuple(fh.read(2))
    if version == (1, 0):
        header_len = struct.unpack("<H", fh.read(2))[0]
    elif version in {(2, 0), (3, 0)}:
        header_len = struct.unpack("<I", fh.read(4))[0]
    else:
        raise RuntimeError(f"unsupported NPY version {version}")
    return ast.literal_eval(fh.read(header_len).decode("latin1"))

def copy_npy_u8(zf: zipfile.ZipFile, member: str, out: Path, expected_shape: tuple[int, ...]) -> dict:
    expected_values = reduce(mul, expected_shape, 1)
    remaining = expected_values
    distinct = set()
    min_value = 255
    max_value = 0
    with zf.open(member) as fh, out.open("wb") as dst:
        header = read_npy_header(fh)
        if header.get("descr") != "|u1" or header.get("fortran_order") is not False or tuple(header.get("shape", ())) != expected_shape:
            raise RuntimeError(f"{member}: unexpected NPY header {header}")
        while remaining:
            chunk = fh.read(min(1 << 20, remaining))
            if not chunk:
                raise RuntimeError(f"{member}: truncated image payload")
            dst.write(chunk)
            distinct.update(chunk)
            min_value = min(min_value, min(chunk))
            max_value = max(max_value, max(chunk))
            remaining -= len(chunk)
        if fh.read(1):
            raise RuntimeError(f"{member}: extra bytes after image payload")
    if len(distinct) < 2:
        raise RuntimeError(f"{member}: degenerate constant image payload")
    return {"member": member, "file": rel(out), "shape": list(expected_shape), "values": expected_values, "bytes": expected_values, "min": min_value, "max": max_value, "distinct_values": len(distinct), "sha256": sha256_file(out)}

images_dir = samples_dir / "pathmnist_images"
reset_dir(images_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

splits = [
    ("train", "train_images.npy", (89996, 28, 28, 3)),
    ("val", "val_images.npy", (10004, 28, 28, 3)),
    ("test", "test_images.npy", (7180, 28, 28, 3)),
]
stats = {"dataset_id": DATASET_ID, "splits": []}
rows = []
with zipfile.ZipFile(archive) as zf:
    for split, member, shape in splits:
        out = images_dir / f"{split}_images_u8.bin"
        split_stats = copy_npy_u8(zf, member, out, shape)
        stats["splits"].append({"split": split, "images": split_stats})
        rows.append({"dataset_id": DATASET_ID, "series_id": "pathmnist_images", "sample_path": rel(out), "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": out.stat().st_size, "value_count": out.stat().st_size})

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
