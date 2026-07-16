#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_steel_plates_faults_features_f64"
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

import json
import math
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "uci_steel_plates_faults_features_f64"
SOURCE_FILE = "Faults.NNA"
EXPECTED_COLUMNS = 34
FEATURE_COLUMNS = 27
MAX_PRIMARY_BYTES = 1_000_000_000
MIN_VALUES_PER_SAMPLE = 1_000
MIN_SAMPLES = 27

FEATURE_NAMES = [
    "X_Minimum",
    "X_Maximum",
    "Y_Minimum",
    "Y_Maximum",
    "Pixels_Areas",
    "X_Perimeter",
    "Y_Perimeter",
    "Sum_of_Luminosity",
    "Minimum_of_Luminosity",
    "Maximum_of_Luminosity",
    "Length_of_Conveyer",
    "TypeOfSteel_A300",
    "TypeOfSteel_A400",
    "Steel_Plate_Thickness",
    "Edges_Index",
    "Empty_Index",
    "Square_Index",
    "Outside_X_Index",
    "Edges_X_Index",
    "Edges_Y_Index",
    "Outside_Global_Index",
    "LogOfAreas",
    "Log_X_Index",
    "Log_Y_Index",
    "Orientation_Index",
    "Luminosity_Index",
    "SigmoidOfAreas",
]

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
source_path = download_dir / SOURCE_FILE
if not source_path.is_file():
    raise SystemExit(f"missing source file: {source_path}")


def slug(text: str) -> str:
    return "_".join("".join(ch.lower() if ch.isalnum() else "_" for ch in text).split("_"))


if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

columns = {name: [] for name in FEATURE_NAMES}
rows_seen = 0
bad_rows = 0
with source_path.open("r", encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != EXPECTED_COLUMNS:
            bad_rows += 1
            continue
        try:
            values = [float(part) for part in parts]
        except ValueError:
            bad_rows += 1
            continue
        if any(not math.isfinite(value) for value in values):
            bad_rows += 1
            continue
        labels = values[FEATURE_COLUMNS:]
        if any(label not in (0.0, 1.0) for label in labels) or sum(labels) != 1.0:
            bad_rows += 1
            continue
        for name, value in zip(FEATURE_NAMES, values[:FEATURE_COLUMNS]):
            columns[name].append(value)
        rows_seen += 1

rows = []
records = []
total_bytes = 0
for index, name in enumerate(FEATURE_NAMES):
    values = columns[name]
    if len(values) < MIN_VALUES_PER_SAMPLE:
        raise SystemExit(f"too few values for {name}: {len(values)}")
    if len(set(values)) <= 1:
        raise SystemExit(f"constant values for {name}")
    series_id = f"steel_plates_faults_{slug(name)}_f64"
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_n{len(values):06d}.bin"
    out.write_bytes(struct.pack("<" + "d" * len(values), *values))
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
        "value_count": len(values),
        "sample_format": "raw homogeneous float64 steel fault feature column",
        "sample_geometry": "table_column",
        "sample_rank": 1,
        "sample_shape": [len(values)],
        "sample_axes": ["fault_region"],
        "natural_record_kind": "uci_steel_plate_fault_feature_column",
        "source_file": SOURCE_FILE,
        "source_column_index": index,
        "source_field": name,
        "min": min(values),
        "max": max(values),
    }
    rows.append(row)
    records.append({
        "series_id": series_id,
        "source_field": name,
        "source_column_index": index,
        "values": len(values),
        "sample_bytes": size,
        "min": min(values),
        "max": max(values),
    })

if len(rows) < MIN_SAMPLES:
    raise SystemExit(f"too few accepted samples: {len(rows)} < {MIN_SAMPLES}")
counts = sorted(int(row["value_count"]) for row in rows)
stats = {
    "dataset_id": DATASET_ID,
    "rows_seen": rows_seen,
    "bad_rows": bad_rows,
    "samples": len(rows),
    "primary_values": sum(counts),
    "primary_sample_bytes": total_bytes,
    "median_value_count": statistics.median(counts),
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
    "records": records,
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
