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
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import zipfile
from collections import Counter
from pathlib import Path

DATASET_ID = "uci_letter_recognition_u8"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive = download_dir / "letter-recognition.zip"

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

features_dir = samples_dir / "letter_ocr_features"
labels_dir = samples_dir / "letter_labels_ascii"
reset_dir(features_dir)
reset_dir(labels_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
features_out = features_dir / "letter_ocr_features_u8.bin"
labels_out = labels_dir / "letter_labels_ascii_u8.bin"

feature_values = bytearray()
label_values = bytearray()
feature_counts = Counter()
label_counts = Counter()
with zipfile.ZipFile(archive) as zf:
    with zf.open("letter-recognition.data") as raw:
        for row_number, row in enumerate(csv.reader(line.decode("ascii") for line in raw), start=1):
            if len(row) != 17:
                raise RuntimeError(f"row {row_number}: expected 17 columns, got {len(row)}")
            label = row[0]
            if len(label) != 1 or not ("A" <= label <= "Z"):
                raise RuntimeError(f"row {row_number}: invalid label {label!r}")
            label_byte = ord(label)
            label_values.append(label_byte)
            label_counts[label] += 1
            for column, value in enumerate(row[1:], start=1):
                try:
                    ivalue = int(value)
                except ValueError as exc:
                    raise RuntimeError(f"row {row_number} col {column}: non-integer {value!r}") from exc
                if ivalue < 0 or ivalue > 15:
                    raise RuntimeError(f"row {row_number} col {column}: feature out of range {ivalue}")
                feature_values.append(ivalue)
                feature_counts[ivalue] += 1

if len(label_values) != 20000:
    raise RuntimeError(f"unexpected row count {len(label_values)}")
if len(feature_values) != 20000 * 16:
    raise RuntimeError(f"unexpected feature value count {len(feature_values)}")
if len(set(feature_values)) < 2 or len(set(label_values)) < 2:
    raise RuntimeError("degenerate feature or label payload")

features_out.write_bytes(feature_values)
labels_out.write_bytes(label_values)
stats = {
    "dataset_id": DATASET_ID,
    "rows": len(label_values),
    "features_per_row": 16,
    "feature_file": rel(features_out),
    "feature_values": len(feature_values),
    "feature_min": min(feature_values),
    "feature_max": max(feature_values),
    "feature_distinct_values": len(feature_counts),
    "feature_sha256": sha256_file(features_out),
    "label_file": rel(labels_out),
    "label_values": len(label_values),
    "label_distinct_values": len(label_counts),
    "label_sha256": sha256_file(labels_out),
}
rows = [
    {
        "dataset_id": DATASET_ID,
        "series_id": "letter_ocr_features",
        "sample_path": rel(features_out),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": features_out.stat().st_size,
        "value_count": features_out.stat().st_size,
    },
    {
        "dataset_id": DATASET_ID,
        "series_id": "letter_labels_ascii",
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
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
