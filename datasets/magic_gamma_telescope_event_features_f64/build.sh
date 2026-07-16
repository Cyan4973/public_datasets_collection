#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="magic_gamma_telescope_event_features_f64"
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
import json
import math
import os
import shutil
import struct
from pathlib import Path

DATASET_ID = "magic_gamma_telescope_event_features_f64"
SOURCE_FILE = "magic04.data"
FIELDS = [
    "fLength",
    "fWidth",
    "fSize",
    "fConc",
    "fConc1",
    "fAsym",
    "fM3Long",
    "fM3Trans",
    "fAlpha",
    "fDist",
]
MAX_PRIMARY_BYTES = 1_000_000_000
MIN_VALUES_PER_SAMPLE = 1_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
source = download_dir / SOURCE_FILE
if not source.is_file():
    raise SystemExit(f"missing source file: {source}")


def slug(text: str) -> str:
    return "_".join("".join(ch.lower() if ch.isalnum() else "_" for ch in text).split("_"))


if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

values = {field: [] for field in FIELDS}
rows_seen = 0
bad_rows = 0
with source.open("r", encoding="utf-8", errors="replace", newline="") as fh:
    for record in csv.reader(fh):
        if len(record) != 11:
            bad_rows += 1
            continue
        try:
            parsed = [float(value) for value in record[:10]]
        except ValueError:
            bad_rows += 1
            continue
        if any(not math.isfinite(value) for value in parsed) or record[10] not in {"g", "h"}:
            bad_rows += 1
            continue
        rows_seen += 1
        for field, value in zip(FIELDS, parsed):
            values[field].append(value)

rows = []
stats_records = []
total_bytes = 0
for field in FIELDS:
    field_values = values[field]
    if len(field_values) < MIN_VALUES_PER_SAMPLE or len(set(field_values)) <= 1:
        continue
    series_id = f"magic_gamma_{slug(field)}_f64"
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_n{len(field_values):06d}.bin"
    out.write_bytes(struct.pack("<" + "d" * len(field_values), *field_values))
    size = out.stat().st_size
    total_bytes += size
    if total_bytes > MAX_PRIMARY_BYTES:
        raise RuntimeError(f"primary output exceeds cap: {total_bytes}")
    row = {
        "dataset_id": DATASET_ID,
        "series_id": series_id,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": size,
        "value_count": len(field_values),
        "sample_format": "raw homogeneous float64 Cherenkov event feature column",
        "sample_geometry": "table_column",
        "sample_rank": 1,
        "sample_shape": [len(field_values)],
        "sample_axes": ["event"],
        "natural_record_kind": "magic_gamma_telescope_event_feature_column",
        "source_file": SOURCE_FILE,
        "source_field": field,
        "min": min(field_values),
        "max": max(field_values),
    }
    rows.append(row)
    stats_records.append({
        "series_id": series_id,
        "field": field,
        "values": len(field_values),
        "sample_bytes": size,
        "min": min(field_values),
        "max": max(field_values),
    })

if len(rows) != len(FIELDS):
    raise SystemExit(f"expected {len(FIELDS)} feature samples, got {len(rows)}")
counts = sorted(int(row["value_count"]) for row in rows)
stats = {
    "dataset_id": DATASET_ID,
    "rows_seen": rows_seen,
    "bad_rows": bad_rows,
    "samples": len(rows),
    "primary_values": sum(counts),
    "primary_sample_bytes": total_bytes,
    "median_value_count": counts[len(counts) // 2],
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "records": stats_records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(rows, key=lambda item: item["series_id"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built samples={len(rows)} primary_values={stats['primary_values']} "
    f"primary_bytes={total_bytes} median_values={stats['median_value_count']}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
