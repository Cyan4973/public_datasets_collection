#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_stormevents_details_2024_f64"
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

DATASET_ID = "noaa_stormevents_details_2024_f64"
SERIES_ID = "noaa_stormevents_detail_numeric_f64"
REQUIRED_FIELDS = {
    "StormEvents_details.BEGIN_LAT",
    "StormEvents_details.BEGIN_LON",
    "StormEvents_details.END_LAT",
    "StormEvents_details.END_LON",
}

data_root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"

if not index_path.is_file():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
primary = [row for row in rows if row.get("role") == "primary"]
if len(primary) < 5:
    raise SystemExit(f"too few primary samples: {len(primary)}")

counts: list[int] = []
total_bytes = 0
seen_fields: set[str] = set()
for row in primary:
    if row.get("dataset_id") != DATASET_ID:
        raise SystemExit(f"wrong dataset_id: {row.get('dataset_id')}")
    if row.get("series_id") != SERIES_ID:
        raise SystemExit(f"wrong series_id: {row.get('series_id')}")
    if row.get("numeric_kind") != "float" or int(row.get("bit_width")) != 64:
        raise SystemExit(f"wrong numeric type: {row}")
    if row.get("source_format") != "gzip_csv":
        raise SystemExit(f"wrong source_format: {row.get('source_format')}")
    if row.get("natural_record_kind") != "noaa_stormevents_detail_year_field":
        raise SystemExit(f"wrong natural_record_kind: {row.get('natural_record_kind')}")
    source_field = row.get("source_field")
    if source_field in seen_fields:
        raise SystemExit(f"duplicate source field: {source_field}")
    seen_fields.add(source_field)
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {path}")
    size = path.stat().st_size
    if size != int(row["sample_size_bytes"]):
        raise SystemExit(f"size mismatch: {row['sample_path']}")
    if size % 8 != 0 or size // 8 != int(row["value_count"]):
        raise SystemExit(f"value-count mismatch: {row['sample_path']}")
    data = path.read_bytes()
    prefix_count = min(4096, len(data) // 8)
    prefix = struct.unpack("<" + "d" * prefix_count, data[: prefix_count * 8])
    if len(set(prefix)) <= 1 and float(row["min_value"]) == float(row["max_value"]):
        raise SystemExit(f"constant sample: {row['sample_path']}")
    counts.append(int(row["value_count"]))
    total_bytes += size

missing_required = sorted(REQUIRED_FIELDS - seen_fields)
if missing_required:
    raise SystemExit(f"missing required coordinate fields: {missing_required}")
if sum(counts) < 100_000 or total_bytes < 800_000:
    raise SystemExit(f"aggregate floor failed: values={sum(counts)} bytes={total_bytes}")
if statistics.median(counts) < 1_000:
    raise SystemExit(f"median sample below floor: {statistics.median(counts)}")
if total_bytes > 1_000_000_000:
    raise SystemExit(f"primary bytes exceed cap: {total_bytes}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if int(stats["samples"]) != len(primary):
    raise SystemExit(f"stats/index sample mismatch: {stats['samples']} != {len(primary)}")
if int(stats["primary_values"]) != sum(counts):
    raise SystemExit(f"stats/index value mismatch: {stats['primary_values']} != {sum(counts)}")
if int(stats["primary_sample_bytes"]) != total_bytes:
    raise SystemExit(f"stats/index byte mismatch: {stats['primary_sample_bytes']} != {total_bytes}")

print(
    f"verified dataset={DATASET_ID} samples={len(primary)} "
    f"values={sum(counts)} bytes={total_bytes} median={int(statistics.median(counts))}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
