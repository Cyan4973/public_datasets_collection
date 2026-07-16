#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="silso_sunspot_activity_indices_f32"
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
import statistics
import struct
from pathlib import Path

DATASET_ID = "silso_sunspot_activity_indices_f32"
MAX_PRIMARY_BYTES = 1_000_000_000
MIN_VALUES_PER_SAMPLE = 1_000
MIN_SAMPLES = 6

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])


def as_f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def read_field(path: Path, expected_width: int, column: int) -> tuple[list[float], int, int]:
    if not path.is_file():
        raise SystemExit(f"missing source CSV: {path}")
    values: list[float] = []
    rows_seen = 0
    skipped = 0
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        for record in reader:
            if not record or all(not cell.strip() for cell in record):
                continue
            if len(record) != expected_width:
                skipped += 1
                continue
            rows_seen += 1
            try:
                value = float(record[column].strip())
            except ValueError:
                skipped += 1
                continue
            if not math.isfinite(value) or value < 0:
                skipped += 1
                continue
            values.append(as_f32(value))
    return values, rows_seen, skipped


specs = [
    {
        "series_id": "silso_daily_total_sunspot_number_f32",
        "file": "SN_d_tot_V2.0.csv",
        "width": 8,
        "column": 4,
        "cadence": "daily",
        "field": "total_sunspot_number",
        "description": "daily total sunspot number",
        "axis": "day",
    },
    {
        "series_id": "silso_daily_total_standard_deviation_f32",
        "file": "SN_d_tot_V2.0.csv",
        "width": 8,
        "column": 5,
        "cadence": "daily",
        "field": "standard_deviation",
        "description": "daily total sunspot-number standard deviation",
        "axis": "day",
    },
    {
        "series_id": "silso_daily_observation_count_f32",
        "file": "SN_d_tot_V2.0.csv",
        "width": 8,
        "column": 6,
        "cadence": "daily",
        "field": "observation_count",
        "description": "daily contributing observation count",
        "axis": "day",
    },
    {
        "series_id": "silso_monthly_mean_sunspot_number_f32",
        "file": "SN_m_tot_V2.0.csv",
        "width": 7,
        "column": 3,
        "cadence": "monthly",
        "field": "mean_sunspot_number",
        "description": "monthly mean total sunspot number",
        "axis": "month",
    },
    {
        "series_id": "silso_monthly_mean_standard_deviation_f32",
        "file": "SN_m_tot_V2.0.csv",
        "width": 7,
        "column": 4,
        "cadence": "monthly",
        "field": "standard_deviation",
        "description": "monthly mean sunspot-number standard deviation",
        "axis": "month",
    },
    {
        "series_id": "silso_monthly_observation_count_f32",
        "file": "SN_m_tot_V2.0.csv",
        "width": 7,
        "column": 5,
        "cadence": "monthly",
        "field": "observation_count",
        "description": "monthly contributing observation count",
        "axis": "month",
    },
]

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
total_bytes = 0
for spec in specs:
    values, rows_seen, skipped = read_field(download_dir / spec["file"], int(spec["width"]), int(spec["column"]))
    if len(values) < MIN_VALUES_PER_SAMPLE:
        raise SystemExit(f"too few values for {spec['series_id']}: {len(values)}")
    if len(set(values)) <= 1:
        raise SystemExit(f"constant values for {spec['series_id']}")
    series_id = spec["series_id"]
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_n{len(values):06d}.bin"
    out.write_bytes(struct.pack("<" + "f" * len(values), *values))
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
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": size,
        "value_count": len(values),
        "sample_format": "raw homogeneous float32 SILSO sunspot activity field",
        "sample_geometry": "time_series",
        "sample_rank": 1,
        "sample_shape": [len(values)],
        "sample_axes": [spec["axis"]],
        "natural_record_kind": "silso_sunspot_activity_index_field",
        "source_file": spec["file"],
        "source_cadence": spec["cadence"],
        "source_field": spec["field"],
        "source_description": spec["description"],
        "min": min(values),
        "max": max(values),
    }
    rows.append(row)
    records.append({
        "series_id": series_id,
        "source_file": spec["file"],
        "field": spec["field"],
        "rows_seen": rows_seen,
        "values": len(values),
        "skipped_values": skipped,
        "sample_bytes": size,
        "min": min(values),
        "max": max(values),
    })

if len(rows) < MIN_SAMPLES:
    raise SystemExit(f"too few accepted samples: {len(rows)} < {MIN_SAMPLES}")
counts = sorted(int(row["value_count"]) for row in rows)
stats = {
    "dataset_id": DATASET_ID,
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
