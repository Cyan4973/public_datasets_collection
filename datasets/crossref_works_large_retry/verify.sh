#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="crossref_works_large_retry"
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

# Each family is a single column, so it must be large enough for the selector to
# shard into independent samples: require >= 1,000,000 values per family.
MIN_FAMILY_VALUES = 1_000_000
MIN_MEDIAN_VALUES = 1_000
MAX_FAMILY_BYTES = 1_000_000_000
EXPECTED_PRIMARY = {
    "crossref_reference_count_u32",
    "crossref_is_referenced_by_count_u32",
    "crossref_created_ts_u64",
    "crossref_deposited_ts_u64",
    "crossref_indexed_ts_u64",
    "crossref_link_count_u16",
    "crossref_license_count_u16",
    "crossref_member_id_u32",
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

for row in primary_rows:
    if int(row["value_count"]) < MIN_FAMILY_VALUES:
        raise SystemExit(f"family below sharding floor: {row['series_id']} has {row['value_count']} < {MIN_FAMILY_VALUES}")
    if int(row["sample_size_bytes"]) > MAX_FAMILY_BYTES:
        raise SystemExit(f"family bytes exceed cap: {row['series_id']} {row['sample_size_bytes']}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median family values below floor: {median_values}")

value_counts = {row["value_count"] for row in primary_rows}
if len(value_counts) != 1:
    raise SystemExit(f"family value_count mismatch: {sorted(value_counts)}")


def unpack_prefix(path: Path, numeric_kind: str, bit_width: int, count: int, prefix: int) -> tuple:
    code_by_type = {
        ("uint", 8): "B",
        ("uint", 16): "H",
        ("uint", 32): "I",
        ("uint", 64): "Q",
        ("float", 32): "f",
        ("float", 64): "d",
    }
    code = code_by_type[(numeric_kind, bit_width)]
    item = bit_width // 8
    take = min(count, prefix)
    with path.open("rb") as fh:
        data = fh.read(take * item)
    return struct.unpack("<" + code * take, data)


for row in primary_rows:
    sample_path = root / row["sample_path"]
    if not sample_path.is_file():
        raise SystemExit(f"missing primary sample {row['sample_path']}")
    expected = int(row["value_count"]) * (int(row["bit_width"]) // 8)
    if sample_path.stat().st_size != int(row["sample_size_bytes"]) or sample_path.stat().st_size != expected:
        raise SystemExit(f"size mismatch: {row['sample_path']}")
    prefix = unpack_prefix(sample_path, row["numeric_kind"], int(row["bit_width"]), int(row["value_count"]), 100_000)
    if len(set(prefix)) <= 1:
        raise SystemExit(f"constant primary prefix rejected: {row['series_id']}")

print(
    "verified_families="
    f"{len(primary_rows)} rows_kept={stats['rows_kept']} rows_skipped={stats['rows_skipped']} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} values_per_family={int(median_values)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
