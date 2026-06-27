#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gleif_lei_records"
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

DATASET_ID = "gleif_lei_records"
root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
expected = {
    "gleif_entity_creation_days_i32": ("int", 32, 4, "<i"),
    "gleif_initial_registration_days_i32": ("int", 32, 4, "<i"),
    "gleif_last_update_days_i32": ("int", 32, 4, "<i"),
    "gleif_next_renewal_days_i32": ("int", 32, 4, "<i"),
    "gleif_legal_address_line_count_u16": ("uint", 16, 2, "<H"),
    "gleif_other_names_count_u16": ("uint", 16, 2, "<H"),
    "gleif_other_validation_authority_count_u16": ("uint", 16, 2, "<H"),
}
required = {
    "gleif_entity_creation_days_i32",
    "gleif_initial_registration_days_i32",
    "gleif_last_update_days_i32",
    "gleif_legal_address_line_count_u16",
    "gleif_other_names_count_u16",
    "gleif_other_validation_authority_count_u16",
}

if not stats_path.is_file():
    raise SystemExit(f"missing stats: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing index: {index_path}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
primary = [row for row in rows if row.get("role", "primary") == "primary"]
series_seen = {row["series_id"] for row in primary}
if not required <= series_seen:
    raise SystemExit(f"missing required series: {sorted(required - series_seen)}")
unknown = series_seen - set(expected)
if unknown:
    raise SystemExit(f"unexpected series: {sorted(unknown)}")

counts = [int(row["value_count"]) for row in primary]
byte_counts = [int(row["sample_size_bytes"]) for row in primary]
if sum(counts) < 10_000 and sum(byte_counts) < 102_400:
    raise SystemExit(f"below aggregate floor: values={sum(counts)} bytes={sum(byte_counts)}")
if statistics.median(counts) < 1_000:
    raise SystemExit(f"median sample values below floor: {statistics.median(counts)}")

retained = int(stats["retained_records"])
for row in primary:
    series_id = row["series_id"]
    kind, bits, element_size, fmt = expected[series_id]
    if row.get("dataset_id") != DATASET_ID:
        raise SystemExit(f"wrong dataset_id: {row}")
    if row["numeric_kind"] != kind or int(row["bit_width"]) != bits:
        raise SystemExit(f"encoding mismatch: {row['sample_path']}")
    if row["endianness"] != "little" or int(row["element_size_bytes"]) != element_size:
        raise SystemExit(f"element mismatch: {row['sample_path']}")
    if row.get("sample_geometry") != "lei_record_column" or int(row.get("sample_rank", 0)) != 1:
        raise SystemExit(f"geometry mismatch: {row['sample_path']}")
    shape = row.get("sample_shape")
    if not isinstance(shape, list) or len(shape) != 1 or int(shape[0]) != int(row["value_count"]):
        raise SystemExit(f"shape mismatch: {row['sample_path']}")
    if series_id in required and int(row["value_count"]) != retained:
        raise SystemExit(f"required series length mismatch for {series_id}")

    p = root / row["sample_path"]
    if not p.is_file():
        raise SystemExit(f"missing sample {row['sample_path']}")
    data = p.read_bytes()
    if len(data) != int(row["sample_size_bytes"]) or len(data) != int(row["value_count"]) * element_size:
        raise SystemExit(f"size mismatch {row['sample_path']}")
    values = [value for (value,) in struct.iter_unpack(fmt, data)]
    if len(values) != int(row["value_count"]):
        raise SystemExit(f"value count mismatch {row['sample_path']}")
    if min(values) == max(values):
        raise SystemExit(f"constant sample: {row['sample_path']}")
    if abs(float(row["min"]) - float(min(values))) > 1e-9 or abs(float(row["max"]) - float(max(values))) > 1e-9:
        raise SystemExit(f"index min/max mismatch: {row['sample_path']}")

if int(stats["primary_values"]) != sum(counts):
    raise SystemExit("stats primary_values mismatch")
if int(stats["primary_sample_bytes"]) != sum(byte_counts):
    raise SystemExit("stats primary_sample_bytes mismatch")

print(
    f"verified samples={len(primary)} retained_records={retained} "
    f"total_values={sum(counts)} total_bytes={sum(byte_counts)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
