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
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import struct
from pathlib import Path

DATASET_ID = "fashion_mnist_images_u8"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

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

def read_idx_image(src: Path, out: Path, expected_count: int) -> dict:
    with gzip.open(src, "rb") as fh, out.open("wb") as dst:
        header = fh.read(16)
        if len(header) != 16:
            raise RuntimeError(f"{src}: truncated IDX image header")
        magic, count, rows, cols = struct.unpack(">IIII", header)
        if (magic, count, rows, cols) != (2051, expected_count, 28, 28):
            raise RuntimeError(f"{src}: unexpected IDX image header {(magic, count, rows, cols)}")
        expected_bytes = count * rows * cols
        remaining = expected_bytes
        seen = bytearray()
        while remaining:
            chunk = fh.read(min(1 << 20, remaining))
            if not chunk:
                raise RuntimeError(f"{src}: truncated image payload")
            dst.write(chunk)
            seen.extend(chunk)
            remaining -= len(chunk)
        if fh.read(1):
            raise RuntimeError(f"{src}: extra bytes after image payload")
    distinct = len(set(seen))
    if distinct < 2:
        raise RuntimeError(f"{src}: degenerate constant image payload")
    return {
        "source": rel(src),
        "file": rel(out),
        "values": expected_bytes,
        "bytes": expected_bytes,
        "images": count,
        "rows": rows,
        "cols": cols,
        "min": min(seen),
        "max": max(seen),
        "distinct_values": distinct,
        "sha256": sha256_file(out),
    }

def read_idx_labels(src: Path, out: Path, expected_count: int) -> dict:
    with gzip.open(src, "rb") as fh:
        header = fh.read(8)
        if len(header) != 8:
            raise RuntimeError(f"{src}: truncated IDX label header")
        magic, count = struct.unpack(">II", header)
        if (magic, count) != (2049, expected_count):
            raise RuntimeError(f"{src}: unexpected IDX label header {(magic, count)}")
        labels = fh.read(count)
        if len(labels) != count:
            raise RuntimeError(f"{src}: truncated label payload")
        if fh.read(1):
            raise RuntimeError(f"{src}: extra bytes after label payload")
    bad = [v for v in labels if v > 9]
    if bad:
        raise RuntimeError(f"{src}: label outside 0..9")
    out.write_bytes(labels)
    return {
        "source": rel(src),
        "file": rel(out),
        "values": count,
        "bytes": count,
        "min": min(labels),
        "max": max(labels),
        "distinct_values": len(set(labels)),
        "sha256": sha256_file(out),
    }

images_dir = samples_dir / "fashion_mnist_images"
labels_dir = samples_dir / "fashion_mnist_labels"
reset_dir(images_dir)
reset_dir(labels_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

splits = [
    ("train", 60000, "train-images-idx3-ubyte.gz", "train-labels-idx1-ubyte.gz"),
    ("test", 10000, "t10k-images-idx3-ubyte.gz", "t10k-labels-idx1-ubyte.gz"),
]
stats = {"dataset_id": DATASET_ID, "splits": []}
rows = []
for split, count, image_name, label_name in splits:
    image_out = images_dir / f"{split}_images_u8.bin"
    label_out = labels_dir / f"{split}_labels_u8.bin"
    image_stats = read_idx_image(download_dir / image_name, image_out, count)
    label_stats = read_idx_labels(download_dir / label_name, label_out, count)
    stats["splits"].append({"split": split, "images": image_stats, "labels": label_stats})
    rows.append({
        "dataset_id": DATASET_ID,
        "series_id": "fashion_mnist_images",
        "sample_path": rel(image_out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": image_out.stat().st_size,
        "value_count": image_out.stat().st_size,
    })
    rows.append({
        "dataset_id": DATASET_ID,
        "series_id": "fashion_mnist_labels",
        "sample_path": rel(label_out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": label_out.stat().st_size,
        "value_count": label_out.stat().st_size,
    })

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
