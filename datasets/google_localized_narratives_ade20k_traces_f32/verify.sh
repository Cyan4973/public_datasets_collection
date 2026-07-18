#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_localized_narratives_ade20k_traces_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
import struct
from pathlib import Path

DATASET_ID = "google_localized_narratives_ade20k_traces_f32"
FAMILY = "localized_narratives_ade20k_trace_fields"
MIN_TRACE_POINTS = 2_000_000
MIN_PRIMARY_BYTES = 32_000_000
MAX_PRIMARY_BYTES = 1_000_000_000

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
expected_ids = {
    "localized_narratives_trace_x_f32",
    "localized_narratives_trace_y_f32",
    "localized_narratives_trace_time_f32",
    "localized_narratives_points_per_record_u32",
    "localized_narratives_caption_chars_u32",
}
if {row["series_id"] for row in rows} != expected_ids:
    raise SystemExit(f"unexpected series ids: {sorted(row['series_id'] for row in rows)}")

total_bytes = 0
trace_counts = set()
record_counts = set()
points_per_record_values = None
for row in rows:
    if row.get("dataset_id") != DATASET_ID or row.get("family") != FAMILY:
        raise SystemExit(f"unexpected row identity: {row}")
    if row.get("role") != "primary":
        raise SystemExit(f"unexpected role: {row}")
    path = root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    size = path.stat().st_size
    count = int(row["value_count"])
    element = int(row["element_size_bytes"])
    if size != int(row["sample_size_bytes"]) or size != count * element:
        raise SystemExit(f"size/count mismatch: {row['sample_path']}")
    total_bytes += size
    if row["series_id"].startswith("localized_narratives_trace_"):
        trace_counts.add(count)
        if count < MIN_TRACE_POINTS:
            raise SystemExit(f"trace stream below floor: {row['series_id']} {count}")
        sample = path.read_bytes()[: min(size, 4 * 250000)]
        values = struct.iter_unpack("<f", sample[: len(sample) - (len(sample) % 4)])
        seen = set()
        for (value,) in values:
            if not math.isfinite(value):
                raise SystemExit(f"non-finite trace value in {row['sample_path']}")
            seen.add(round(value, 6))
            if row["series_id"] in {"localized_narratives_trace_x_f32", "localized_narratives_trace_y_f32"}:
                if not (0.0 <= value <= 1.0):
                    raise SystemExit(f"coordinate out of range in {row['sample_path']}: {value}")
            else:
                if value < 0.0:
                    raise SystemExit(f"negative trace time in {row['sample_path']}: {value}")
        if len(seen) < 100:
            raise SystemExit(f"trace sample appears low-variety: {row['sample_path']}")
    else:
        record_counts.add(count)
        data = path.read_bytes()
        values = list(struct.iter_unpack("<I", data))
        if not values:
            raise SystemExit(f"empty uint32 stream: {row['sample_path']}")
        ints = [value for (value,) in values]
        if row["series_id"] == "localized_narratives_points_per_record_u32":
            points_per_record_values = ints
            if sum(ints) != int(stats["trace_points"]):
                raise SystemExit("points-per-record stream does not sum to trace_points")
            if max(ints) <= 0:
                raise SystemExit("points-per-record stream has no positive records")
        elif row["series_id"] == "localized_narratives_caption_chars_u32":
            if max(ints) <= 0:
                raise SystemExit("caption length stream has no positive values")

if len(trace_counts) != 1:
    raise SystemExit(f"trace stream count mismatch: {trace_counts}")
if len(record_counts) != 1:
    raise SystemExit(f"record stream count mismatch: {record_counts}")
if points_per_record_values is None:
    raise SystemExit("missing points-per-record values")
if sum(1 for value in points_per_record_values if value > 0) != int(stats["trace_records"]):
    raise SystemExit("trace_records does not match positive points-per-record values")
if total_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {total_bytes} < {MIN_PRIMARY_BYTES}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes} > {MAX_PRIMARY_BYTES}")
if int(stats["primary_sample_bytes"]) != total_bytes:
    raise SystemExit("stats/index byte mismatch")

print(
    f"verified dataset={DATASET_ID} samples={len(rows)} "
    f"trace_points={next(iter(trace_counts))} primary_bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
