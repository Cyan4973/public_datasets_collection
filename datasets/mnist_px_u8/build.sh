#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="mnist_px_u8"
FAMILY="mnist_pixel_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
MIN_RECORDS="${MNIST_MIN_RECORDS:-1000}"
export REPO_ROOT DATA_DIR DATASET_ID FAMILY DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_RECORDS
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
import shutil
import struct
from collections import defaultdict
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
DATASET_ID = os.environ["DATASET_ID"]
FAMILY = os.environ["FAMILY"]
min_records = int(os.environ["MIN_RECORDS"])

SPLITS = {"train": ("train-images-idx3-ubyte.gz", "train-labels-idx1-ubyte.gz"),
          "test": ("t10k-images-idx3-ubyte.gz", "t10k-labels-idx1-ubyte.gz")}


def read_idx_images(path: Path):
    raw = gzip.decompress(path.read_bytes())
    magic, n, rows, cols = struct.unpack(">IIII", raw[:16])
    if magic != 0x00000803:
        raise SystemExit(f"bad image idx magic {magic:#x} in {path}")
    body = raw[16:]
    if len(body) != n * rows * cols:
        raise SystemExit(f"image body size mismatch in {path}")
    return n, rows, cols, body


def read_idx_labels(path: Path):
    raw = gzip.decompress(path.read_bytes())
    magic, n = struct.unpack(">II", raw[:8])
    if magic != 0x00000801:
        raise SystemExit(f"bad label idx magic {magic:#x} in {path}")
    body = raw[8:]
    if len(body) != n:
        raise SystemExit(f"label body size mismatch in {path}")
    return n, body


# bucket: (split, label) -> bytearray of concatenated pixels
buckets = defaultdict(bytearray)
geom = None
for split, (imgf, lblf) in SPLITS.items():
    n, rows, cols, body = read_idx_images(download_dir / imgf)
    nl, labels = read_idx_labels(download_dir / lblf)
    if n != nl:
        raise SystemExit(f"{split}: image/label count mismatch {n} vs {nl}")
    geom = (rows, cols)
    px = rows * cols
    mv = memoryview(body)
    for i in range(n):
        lab = labels[i]
        buckets[(split, lab)] += mv[i * px:(i + 1) * px]

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_fam = samples_dir / FAMILY
out_fam.mkdir(parents=True, exist_ok=True)

index_rows = []
for (split, lab), buf in sorted(buckets.items()):
    if len(buf) < min_records or len(set(buf)) <= 1:
        continue
    out = out_fam / f"{FAMILY}_{split}_c{lab}_n{len(buf):07d}.bin"
    out.write_bytes(bytes(buf))
    index_rows.append({
        "dataset_id": DATASET_ID,
        "series_id": FAMILY,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": out.stat().st_size,
        "value_count": len(buf),
        "sample_geometry": "sequence",
        "sample_rank": 1,
        "split": split,
        "class_label": lab,
        "natural_record_kind": "image_class_pixels",
    })

if len(index_rows) < 5:
    raise SystemExit(f"only {len(index_rows)} samples qualified")

counts = sorted(r["value_count"] for r in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "family": FAMILY,
    "image_geometry": {"rows": geom[0], "cols": geom[1]},
    "samples": len(index_rows),
    "primary_values": sum(counts),
    "primary_sample_bytes": sum(r["sample_size_bytes"] for r in index_rows),
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r: r["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built family={FAMILY} samples={len(index_rows)} geom={geom} "
      f"primary_values={sum(counts)} median={median} range=[{counts[0]},{counts[-1]}]")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
