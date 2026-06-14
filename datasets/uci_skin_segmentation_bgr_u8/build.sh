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
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from collections import Counter
from pathlib import Path

DATASET_ID = "uci_skin_segmentation_bgr_u8"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive = download_dir / "skin-segmentation.zip"

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

bgr_dir = samples_dir / "skin_bgr_channels"
labels_dir = samples_dir / "skin_binary_labels"
reset_dir(bgr_dir)
reset_dir(labels_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
bgr_out = bgr_dir / "skin_bgr_channels_u8.bin"
labels_out = labels_dir / "skin_binary_labels_u8.bin"

bgr_payload = bytearray()
label_payload = bytearray()
bgr_counts = Counter()
label_counts = Counter()
with zipfile.ZipFile(archive) as zf:
    members = [name for name in zf.namelist() if not name.endswith("/") and name.lower().endswith((".txt", ".data", ".csv"))]
    if len(members) != 1:
        raise RuntimeError(f"expected one data table member, found {members}")
    member = members[0]
    with zf.open(member) as raw:
        for line_number, raw_line in enumerate(raw, start=1):
            line = raw_line.decode("ascii").strip()
            if not line:
                continue
            values = [int(part) for part in line.replace(",", " ").split()]
            if len(values) != 4:
                raise RuntimeError(f"line {line_number}: expected 4 columns, got {len(values)}")
            for value in values[:3]:
                if value < 0 or value > 255:
                    raise RuntimeError(f"line {line_number}: BGR value outside uint8 range")
                bgr_payload.append(value)
                bgr_counts[value] += 1
            label = values[3]
            if label not in {1, 2}:
                raise RuntimeError(f"line {line_number}: label outside 1..2")
            label_payload.append(label)
            label_counts[label] += 1

rows = len(label_payload)
if rows != 245057:
    raise RuntimeError(f"unexpected row count {rows}")
if len(bgr_payload) != rows * 3:
    raise RuntimeError(f"unexpected BGR value count {len(bgr_payload)}")
if len(bgr_counts) < 2 or len(label_counts) < 2:
    raise RuntimeError("degenerate BGR or label payload")

bgr_out.write_bytes(bgr_payload)
labels_out.write_bytes(label_payload)
stats = {
    "dataset_id": DATASET_ID,
    "source_member": member,
    "rows": rows,
    "channels_per_row": 3,
    "bgr_file": rel(bgr_out),
    "bgr_values": len(bgr_payload),
    "bgr_min": min(bgr_counts),
    "bgr_max": max(bgr_counts),
    "bgr_distinct_values": len(bgr_counts),
    "bgr_sha256": sha256_file(bgr_out),
    "label_file": rel(labels_out),
    "label_values": len(label_payload),
    "label_distinct_values": len(label_counts),
    "label_sha256": sha256_file(labels_out),
}
sample_rows = [
    {
        "dataset_id": DATASET_ID,
        "series_id": "skin_bgr_channels",
        "sample_path": rel(bgr_out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": bgr_out.stat().st_size,
        "value_count": bgr_out.stat().st_size,
    },
    {
        "dataset_id": DATASET_ID,
        "series_id": "skin_binary_labels",
        "sample_path": rel(labels_out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": labels_out.stat().st_size,
        "value_count": labels_out.stat().st_size,
    },
]
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
