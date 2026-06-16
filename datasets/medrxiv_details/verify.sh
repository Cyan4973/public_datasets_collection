#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="medrxiv_details"
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
import os
import statistics
import struct
from pathlib import Path

DATASET_ID = "medrxiv_details"
EXPECTED = {
    "medrxiv_details_version": ("primary", "H", 2),
    "medrxiv_details_author_count": ("primary", "H", 2),
    "medrxiv_details_abstract_length": ("primary", "I", 4),
    "medrxiv_details_title_length": ("primary", "H", 2),
    "medrxiv_details_corresponding_institution_length": ("primary", "H", 2),
    "medrxiv_details_date": ("auxiliary", "I", 4),
}
MIN_RECORDS = 10_000
MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
stats = json.loads((Path(os.environ["FILTER_DIR"]) / "ingest_stats.json").read_text(encoding="utf-8"))
rows = [json.loads(line) for line in (Path(os.environ["INDEX_DIR"]) / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
if {row["series_id"] for row in rows} != set(EXPECTED):
    raise SystemExit(f"unexpected series set: {sorted(row['series_id'] for row in rows)}")
if int(stats.get("kept_records", 0)) < MIN_RECORDS:
    raise SystemExit(f"kept records below repair floor: {stats.get('kept_records')}")

primary_counts = []
primary_sizes = []
decoded = {}
for row in rows:
    sid = row["series_id"]
    role, code, element_size = EXPECTED[sid]
    if row["dataset_id"] != DATASET_ID or row.get("role") != role:
        raise SystemExit(f"unexpected dataset/role row: {row}")
    if row["numeric_kind"] != "uint" or int(row["element_size_bytes"]) != element_size:
        raise SystemExit(f"unexpected numeric row: {row}")
    path = root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample {row['sample_path']}")
    expected_size = int(row["sample_size_bytes"])
    expected_count = int(row["value_count"])
    if path.stat().st_size != expected_size or expected_size != expected_count * element_size:
        raise SystemExit(f"size/count mismatch {row['sample_path']}")
    values = struct.unpack("<" + code * expected_count, path.read_bytes())
    if expected_count != int(stats["kept_records"]):
        raise SystemExit(f"series/count mismatch for {sid}: {expected_count} vs {stats['kept_records']}")
    if role == "primary":
        if len(set(values)) <= 1:
            raise SystemExit(f"constant primary series rejected: {sid}")
        primary_counts.append(expected_count)
        primary_sizes.append(expected_size)
    decoded[sid] = values

primary_values = sum(primary_counts)
primary_bytes = sum(primary_sizes)
median_values = statistics.median(primary_counts)
if primary_values < MIN_PRIMARY_VALUES:
    raise SystemExit(f"primary values below floor: {primary_values}")
if primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {primary_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median primary sample values below floor: {median_values}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")
if primary_values != int(stats["primary_values"]) or primary_bytes != int(stats["primary_bytes"]):
    raise SystemExit("stats/index primary total mismatch")
dates = decoded["medrxiv_details_date"]
if any(a > b for a, b in zip(dates, dates[1:])):
    raise SystemExit("date sequence is not sorted")

print(
    f"verified_samples={len(rows)} kept_records={stats['kept_records']} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_values={int(median_values)} source_bytes={stats.get('source_bytes', 0)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
