#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="natural_earth_10m_geometry_xy_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
mkdir -p "$LOG_DIR" "$INDEX_DIR" "$FILTER_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR INDEX_DIR FILTER_DIR
python3 - <<'PY'
from __future__ import annotations

from array import array
import json
import math
import os
import statistics
from pathlib import Path

DATASET_ID = "natural_earth_10m_geometry_xy_f64"
SERIES_ID = "natural_earth_10m_feature_xy_f64"
MIN_VALUES = 10_000
MIN_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
COORD_EPSILON = 1e-9

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"

if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if not rows:
    raise SystemExit("no sample rows")
sizes: list[int] = []
values: list[int] = []
shape_types: set[int] = set()
source_records: set[tuple[str, int]] = set()

for row in rows:
    if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
        raise SystemExit(f"unexpected dataset/series row: {row}")
    if row.get("role") != "primary":
        raise SystemExit(f"unexpected non-primary row: {row}")
    if row.get("numeric_kind") != "float" or row.get("bit_width") != 64 or row.get("endianness") != "little":
        raise SystemExit(f"unexpected numeric representation: {row}")
    if row.get("sample_geometry") != "shapefile_feature_xy_pairs":
        raise SystemExit(f"unexpected sample_geometry: {row}")
    if row.get("natural_record_kind") != "natural_earth_shapefile_feature_geometry":
        raise SystemExit(f"unexpected natural_record_kind: {row}")
    shape_type = int(row.get("source_shape_type"))
    if shape_type not in {3, 5}:
        raise SystemExit(f"point or unsupported shape type reached primary output: {row}")
    shape_types.add(shape_type)
    key = (str(row.get("source_member")), int(row.get("source_record_number")))
    if key in source_records:
        raise SystemExit(f"duplicate source record in output: {key}")
    source_records.add(key)

    sample_path = data_root / row["sample_path"]
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    actual_size = sample_path.stat().st_size
    sample_size = int(row["sample_size_bytes"])
    value_count = int(row["value_count"])
    if actual_size != sample_size:
        raise SystemExit(f"size mismatch for {sample_path}: {actual_size} != {sample_size}")
    if sample_size != value_count * 8:
        raise SystemExit(f"value/byte mismatch for {sample_path}")
    if value_count < MIN_MEDIAN_VALUES or value_count % 2 != 0:
        raise SystemExit(f"bad coordinate value count for {sample_path}: {value_count}")
    point_count = int(row["point_count"])
    if value_count != point_count * 2:
        raise SystemExit(f"point/value mismatch for {sample_path}")
    payload = array("d")
    with sample_path.open("rb") as fh:
        payload.fromfile(fh, value_count)
    for index in range(0, len(payload), 2):
        x = payload[index]
        y = payload[index + 1]
        if not (math.isfinite(x) and math.isfinite(y)):
            raise SystemExit(f"non-finite coordinate in {sample_path}")
        if not (
            -180.0 - COORD_EPSILON <= x <= 180.0 + COORD_EPSILON
            and -90.0 - COORD_EPSILON <= y <= 90.0 + COORD_EPSILON
        ):
            raise SystemExit(f"coordinate outside lon/lat range in {sample_path}: {x},{y}")
    if min(payload) == max(payload):
        raise SystemExit(f"constant sample should not be accepted: {sample_path}")
    sizes.append(sample_size)
    values.append(value_count)

total_bytes = sum(sizes)
total_values = sum(values)
if total_values < MIN_VALUES:
    raise SystemExit(f"primary value floor failed: {total_values} < {MIN_VALUES}")
if total_bytes < MIN_BYTES:
    raise SystemExit(f"primary byte floor failed: {total_bytes} < {MIN_BYTES}")
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary payload exceeds cap: {total_bytes}")
if statistics.median(values) < MIN_MEDIAN_VALUES:
    raise SystemExit("median primary sample size below floor")
if len(set(sizes)) < 2:
    raise SystemExit("selected samples have identical sizes")
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats.get("sample_count") != len(rows) or stats.get("total_values") != total_values or stats.get("total_bytes") != total_bytes:
    raise SystemExit("ingest stats do not match sample index")
print(
    "verified_rows={} primary_values={} primary_bytes={} value_range={}/{}/{} shape_types={}".format(
        len(rows),
        total_values,
        total_bytes,
        min(values),
        int(statistics.median(values)),
        max(values),
        ",".join(str(value) for value in sorted(shape_types)),
    )
)
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
