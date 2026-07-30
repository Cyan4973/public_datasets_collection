#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="uci_dorothea_binary_molecular_features_u8"
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
from pathlib import Path

DATASET_ID = "uci_dorothea_binary_molecular_features_u8"
SERIES_ID = "dorothea_molecular_feature_vector_u8"
FEATURE_COUNT = 100_000
EXPECTED_SPLITS = {"train": 800, "valid": 350, "test": 800}

data_root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.is_file():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
primary = [row for row in rows if row.get("role") == "primary"]
if len(primary) != sum(EXPECTED_SPLITS.values()):
    raise SystemExit(f"primary sample count={len(primary)} expected={sum(EXPECTED_SPLITS.values())}")

split_counts = {split: 0 for split in EXPECTED_SPLITS}
seen_records: set[tuple[str, int]] = set()
active_counts: list[int] = []
total_bytes = 0
for row in primary:
    if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
        raise SystemExit(f"wrong dataset/series identity: {row}")
    if row.get("numeric_kind") != "uint" or int(row.get("bit_width", -1)) != 8:
        raise SystemExit(f"wrong numeric type: {row}")
    if int(row.get("element_size_bytes", -1)) != 1 or row.get("endianness") != "little":
        raise SystemExit(f"wrong physical representation: {row}")
    if row.get("source_format") != "whitespace_delimited_sparse_binary_index_rows":
        raise SystemExit(f"wrong source_format: {row.get('source_format')}")
    if row.get("source_field") != "documented_100000_binary_molecular_input_features":
        raise SystemExit(f"wrong source_field: {row.get('source_field')}")
    if row.get("natural_record_kind") != "dorothea_compound_feature_vector":
        raise SystemExit(f"wrong natural_record_kind: {row.get('natural_record_kind')}")
    split = row.get("source_split")
    source_row = int(row.get("source_row_number", -1))
    record = (split, source_row)
    if split not in EXPECTED_SPLITS or record in seen_records:
        raise SystemExit(f"invalid or duplicate source record: {record}")
    seen_records.add(record)
    split_counts[split] += 1
    sample = data_root / row["sample_path"]
    if not sample.is_file():
        raise SystemExit(f"missing sample: {sample}")
    data = sample.read_bytes()
    if len(data) != FEATURE_COUNT:
        raise SystemExit(f"wrong vector size file={sample} bytes={len(data)}")
    if len(data) != int(row["sample_size_bytes"]) or len(data) != int(row["value_count"]):
        raise SystemExit(f"sample/index size mismatch: {sample}")
    values = set(data)
    if values != {0, 1}:
        raise SystemExit(f"not a nonconstant binary vector file={sample} values={sorted(values)}")
    active = data.count(1)
    if active != int(row["one_count"]) or FEATURE_COUNT - active != int(row["zero_count"]):
        raise SystemExit(f"binary histogram/index mismatch: {sample}")
    active_counts.append(active)
    total_bytes += len(data)

if split_counts != EXPECTED_SPLITS:
    raise SystemExit(f"split counts mismatch: {split_counts}")
total_values = len(primary) * FEATURE_COUNT
median = statistics.median([FEATURE_COUNT] * len(primary))
if total_values < 10_000 and total_bytes < 100 * 1024:
    raise SystemExit(f"aggregate floor failed: values={total_values} bytes={total_bytes}")
if median < 1_000:
    raise SystemExit(f"median natural sample below floor: {median}")
if total_bytes > 1_000_000_000:
    raise SystemExit(f"primary byte cap exceeded: {total_bytes}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if int(stats["samples"]) != len(primary):
    raise SystemExit("stats sample count mismatch")
if int(stats["primary_values"]) != total_values or int(stats["primary_sample_bytes"]) != total_bytes:
    raise SystemExit("stats primary totals mismatch")
if int(stats["active_features"]) != sum(active_counts):
    raise SystemExit("stats active-feature total mismatch")

print(
    f"verified dataset={DATASET_ID} samples={len(primary)} values={total_values} "
    f"bytes={total_bytes} active_min={min(active_counts)} "
    f"active_median={statistics.median(active_counts):.1f} active_max={max(active_counts)} "
    f"one_fraction={sum(active_counts)/total_values:.8f}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
