#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="metacpan_releases_search_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
import struct
from pathlib import Path

MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 262_144
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
MIN_ROWS_KEPT = 90_000
EXPECTED_PRIMARY = {
    "metacpan_version_numified",
    "metacpan_stat_size",
    "metacpan_stat_mtime",
    "metacpan_dependency_count",
    "metacpan_provides_count",
    "metacpan_tests_pass",
    "metacpan_tests_fail",
    "metacpan_tests_na",
    "metacpan_tests_unknown",
}

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
stats = json.loads(stats_path.read_text())

primary_rows = [row for row in rows if row.get("role", "primary") == "primary"]
primary_ids = {row["series_id"] for row in primary_rows}
if primary_ids != EXPECTED_PRIMARY:
    raise SystemExit(f"unexpected primary series: {sorted(primary_ids)}")

primary_values = sum(int(row["value_count"]) for row in primary_rows)
primary_bytes = sum(int(row["sample_size_bytes"]) for row in primary_rows)
median_values = statistics.median(int(row["value_count"]) for row in primary_rows)
if stats.get("rows_kept", 0) < MIN_ROWS_KEPT:
    raise SystemExit(f"rows_kept below floor: {stats.get('rows_kept')} < {MIN_ROWS_KEPT}")
if primary_values < MIN_PRIMARY_VALUES:
    raise SystemExit(f"primary_values below floor: {primary_values}")
if primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary_bytes below stricter repair floor: {primary_bytes} < {MIN_PRIMARY_BYTES}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median primary sample values below floor: {median_values}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary_bytes too large: {primary_bytes}")

value_counts = {row["value_count"] for row in primary_rows}
if len(value_counts) != 1:
    raise SystemExit(f"series value_count mismatch: {sorted(value_counts)}")


def unpack_values(path: Path, numeric_kind: str, bit_width: int, count: int) -> tuple:
    code_by_type = {
        ("uint", 8): "B",
        ("uint", 16): "H",
        ("uint", 32): "I",
        ("float", 32): "f",
        ("float", 64): "d",
    }
    code = code_by_type[(numeric_kind, bit_width)]
    data = path.read_bytes()
    expected_bytes = count * (bit_width // 8)
    if len(data) != expected_bytes:
        raise SystemExit(f"size mismatch for {path}: got={len(data)} expected={expected_bytes}")
    return struct.unpack("<" + code * count, data)


for row in primary_rows:
    sample_path = root / row["sample_path"]
    if not sample_path.is_file():
        raise SystemExit(f"missing primary sample {row['sample_path']}")
    values = unpack_values(sample_path, row["numeric_kind"], int(row["bit_width"]), int(row["value_count"]))
    if len(set(values)) <= 1:
        raise SystemExit(f"constant primary series rejected: {row['series_id']}")

print(
    "verified_samples="
    f"{len(primary_rows)} rows_kept={stats['rows_kept']} rows_skipped={stats['rows_skipped']} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} median_values={median_values}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
