#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_optdigits_u8"
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

DATASET_ID = "uci_optdigits_u8"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
archive = download_dir / "optdigits.zip"

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

features_dir = samples_dir / "optdigits_features"
labels_dir = samples_dir / "optdigits_labels"
reset_dir(features_dir)
reset_dir(labels_dir)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

splits = [("train", "optdigits.tra", 3823), ("test", "optdigits.tes", 1797)]
stats = {"dataset_id": DATASET_ID, "splits": []}
sample_rows = []
with zipfile.ZipFile(archive) as zf:
    base_to_name = {Path(name).name: name for name in zf.namelist() if not name.endswith("/")}
    for split, base, expected_rows in splits:
        feature_payload = bytearray()
        label_payload = bytearray()
        feature_counts = Counter()
        label_counts = Counter()
        member = base_to_name.get(base)
        if member is None:
            raise RuntimeError(f"missing data member {base}")
        with zf.open(member) as raw:
            for line_number, raw_line in enumerate(raw, start=1):
                line = raw_line.decode("ascii").strip()
                if not line:
                    continue
                values = [int(part) for part in line.split(",")]
                if len(values) != 65:
                    raise RuntimeError(f"{base}:{line_number}: expected 65 columns, got {len(values)}")
                for value in values[:64]:
                    if value < 0 or value > 16:
                        raise RuntimeError(f"{base}:{line_number}: feature outside 0..16")
                    feature_payload.append(value)
                    feature_counts[value] += 1
                label = values[64]
                if label < 0 or label > 9:
                    raise RuntimeError(f"{base}:{line_number}: label outside 0..9")
                label_payload.append(label)
                label_counts[label] += 1
        rows = len(label_payload)
        if rows != expected_rows:
            raise RuntimeError(f"{base}: unexpected row count {rows}")
        if len(feature_payload) != rows * 64:
            raise RuntimeError(f"{base}: unexpected feature count {len(feature_payload)}")
        if len(feature_counts) < 2 or len(label_counts) < 2:
            raise RuntimeError(f"{base}: degenerate feature or label payload")
        feature_out = features_dir / f"{split}_optdigits_features_u8.bin"
        label_out = labels_dir / f"{split}_optdigits_labels_u8.bin"
        feature_out.write_bytes(feature_payload)
        label_out.write_bytes(label_payload)
        stats["splits"].append({
            "split": split,
            "source_member": member,
            "rows": rows,
            "feature_values": len(feature_payload),
            "feature_min": min(feature_counts),
            "feature_max": max(feature_counts),
            "feature_distinct_values": len(feature_counts),
            "feature_file": rel(feature_out),
            "feature_sha256": sha256_file(feature_out),
            "label_values": len(label_payload),
            "label_distinct_values": len(label_counts),
            "label_file": rel(label_out),
            "label_sha256": sha256_file(label_out),
        })
        sample_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": "optdigits_features",
            "sample_path": rel(feature_out),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": feature_out.stat().st_size,
            "value_count": feature_out.stat().st_size,
        })
        sample_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": "optdigits_labels",
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
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
