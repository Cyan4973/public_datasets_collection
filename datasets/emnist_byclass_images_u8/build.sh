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
import zipfile
from pathlib import Path

DATASET_ID = "emnist_byclass_images_u8"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive = download_dir / "gzip.zip"

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

def copy_image_member(zf: zipfile.ZipFile, member: str, out: Path, expected_count: int) -> dict:
    values = expected_count * 28 * 28
    distinct = set()
    min_value = 255
    max_value = 0
    remaining = values
    with zf.open(member) as raw, gzip.GzipFile(fileobj=raw) as fh, out.open("wb") as dst:
        got = struct.unpack(">IIII", fh.read(16))
        if got != (2051, expected_count, 28, 28):
            raise RuntimeError(f"{member}: unexpected IDX image header {got}")
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
    return {"member": member, "file": rel(out), "images": expected_count, "values": values, "bytes": values, "min": min_value, "max": max_value, "distinct_values": len(distinct), "sha256": sha256_file(out)}

def copy_label_member(zf: zipfile.ZipFile, member: str, out: Path, expected_count: int) -> dict:
    with zf.open(member) as raw, gzip.GzipFile(fileobj=raw) as fh:
        got = struct.unpack(">II", fh.read(8))
        if got != (2049, expected_count):
            raise RuntimeError(f"{member}: unexpected IDX label header {got}")
        labels = fh.read(expected_count)
        if len(labels) != expected_count:
            raise RuntimeError(f"{member}: truncated label payload")
        if fh.read(1):
            raise RuntimeError(f"{member}: extra bytes after label payload")
    if any(value > 61 for value in labels):
        raise RuntimeError(f"{member}: label outside 0..61")
    out.write_bytes(labels)
    return {"member": member, "file": rel(out), "values": expected_count, "bytes": expected_count, "min": min(labels), "max": max(labels), "distinct_values": len(set(labels)), "sha256": sha256_file(out)}

images_dir = samples_dir / "emnist_byclass_images"
labels_dir = samples_dir / "emnist_byclass_labels"
reset_dir(images_dir)
reset_dir(labels_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

stats = {"dataset_id": DATASET_ID, "splits": []}
rows = []
with zipfile.ZipFile(archive) as zf:
    for split, count in [("train", 697932), ("test", 116323)]:
        image_member = f"gzip/emnist-byclass-{split}-images-idx3-ubyte.gz"
        label_member = f"gzip/emnist-byclass-{split}-labels-idx1-ubyte.gz"
        image_out = images_dir / f"{split}_images_u8.bin"
        label_out = labels_dir / f"{split}_labels_u8.bin"
        image_stats = copy_image_member(zf, image_member, image_out, count)
        label_stats = copy_label_member(zf, label_member, label_out, count)
        stats["splits"].append({"split": split, "images": image_stats, "labels": label_stats})
        rows.append({"dataset_id": DATASET_ID, "series_id": "emnist_byclass_images", "sample_path": rel(image_out), "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": image_out.stat().st_size, "value_count": image_out.stat().st_size})
        rows.append({"dataset_id": DATASET_ID, "series_id": "emnist_byclass_labels", "sample_path": rel(label_out), "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": label_out.stat().st_size, "value_count": label_out.stat().st_size})

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
