#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nyc_311_descriptor_u16"
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
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

csv_path = download_dir / "nyc_311_jan_2024_descriptor.csv"
series_id = "nyc_311_descriptor_id"
series_dir = samples_dir / series_id
MAX_VALUES_PER_SAMPLE = 100000


def rel_data(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if not csv_path.is_file():
    raise RuntimeError(f"missing CSV: {csv_path}")

if series_dir.exists():
    shutil.rmtree(series_dir)
series_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
distinct_descriptors = set()
missing_count = 0
with csv_path.open("r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    if reader.fieldnames != ["unique_key", "descriptor"]:
        raise RuntimeError(f"unexpected CSV header: {reader.fieldnames}")
    for row_num, row in enumerate(reader, start=1):
        unique_key = (row.get("unique_key") or "").strip()
        descriptor = (row.get("descriptor") or "").strip()
        if not unique_key:
            raise RuntimeError(f"row {row_num}: empty unique_key")
        rows.append((unique_key, descriptor))
        if descriptor:
            distinct_descriptors.add(descriptor)
        else:
            missing_count += 1

mapping = {value: idx + 1 for idx, value in enumerate(sorted(distinct_descriptors))}
if len(mapping) > 65535:
    raise RuntimeError(f"descriptor dictionary too large for uint16: {len(mapping)}")

codes = [mapping.get(descriptor, 0) for _, descriptor in rows]
sample_rows = []
outputs = []
stats = {
    "dataset_id": "nyc_311_descriptor_u16",
    "source_csv": rel_data(csv_path),
    "source_sha256": sha256_file(csv_path),
    "rows_total": len(rows),
    "missing_descriptors": missing_count,
    "distinct_nonzero_descriptors": len(mapping),
    "max_values_per_sample": MAX_VALUES_PER_SAMPLE,
    "dictionary_preview": [{"descriptor": key, "code": mapping[key]} for key in sorted(mapping)[:50]],
    "outputs": [],
}

sample_count = math.ceil(len(codes) / MAX_VALUES_PER_SAMPLE)
for shard_idx in range(sample_count):
    start = shard_idx * MAX_VALUES_PER_SAMPLE
    end = min((shard_idx + 1) * MAX_VALUES_PER_SAMPLE, len(codes))
    shard = codes[start:end]
    out_path = series_dir / f"part{shard_idx:03d}.bin"
    out_path.write_bytes(struct.pack("<" + "H" * len(shard), *shard))
    output = {
        "file": rel_data(out_path),
        "part": shard_idx,
        "values": len(shard),
        "bytes": out_path.stat().st_size,
        "offset_values": start,
        "zero_values": sum(1 for value in shard if value == 0),
        "min_code": min(shard) if shard else 0,
        "max_code": max(shard) if shard else 0,
        "sha256": sha256_file(out_path),
    }
    outputs.append(output)
    sample_rows.append({
        "dataset_id": "nyc_311_descriptor_u16",
        "series_id": series_id,
        "sample_path": rel_data(out_path),
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": out_path.stat().st_size,
        "value_count": len(shard),
    })

stats["outputs"] = outputs
stats["series"] = {
    series_id: {
        "files": len(outputs),
        "values": len(codes),
        "bytes": len(codes) * 2,
        "zero_values": missing_count,
        "distinct_nonzero_codes": len(mapping),
        "min_code": min(codes) if codes else 0,
        "max_code": max(codes) if codes else 0,
    }
}

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
