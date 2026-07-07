#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openalex_author_topic_count_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

MIN_VALUES="${OPENALEX_TOPIC_COUNT_VERIFY_MIN_VALUES:-2000000}"
MIN_SAMPLE_VALUES="${OPENALEX_TOPIC_COUNT_VERIFY_MIN_SAMPLE_VALUES:-2000000}"
MAX_PRIMARY_BYTES="${OPENALEX_TOPIC_COUNT_VERIFY_MAX_PRIMARY_BYTES:-1000000000}"

export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR MIN_VALUES MIN_SAMPLE_VALUES MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
min_values = int(os.environ["MIN_VALUES"])
min_sample_values = int(os.environ["MIN_SAMPLE_VALUES"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
stats = json.loads(stats_path.read_text())
if not rows:
    raise SystemExit("empty sample index")
if len(rows) != 1:
    raise SystemExit(f"expected one contiguous stream sample, found {len(rows)}")

total_values = 0
total_bytes = 0
histogram = {}
seen_paths = set()
for row in rows:
    if row.get("series_id") != "openalex_author_topic_count_u8":
        raise SystemExit(f"unexpected series_id: {row.get('series_id')}")
    if row.get("sample_geometry") != "contiguous_author_topic_count_stream":
        raise SystemExit(f"unexpected sample_geometry: {row.get('sample_geometry')}")
    if row.get("numeric_kind") != "uint" or int(row.get("bit_width", 0)) != 8:
        raise SystemExit(f"unexpected numeric type in row: {row}")
    value_count = int(row["value_count"])
    if value_count < min_sample_values:
        raise SystemExit(f"sample below minimum size: {row['sample_path']} has {value_count}")
    sample_path = root / row["sample_path"]
    if sample_path in seen_paths:
        raise SystemExit(f"duplicate sample path: {sample_path}")
    seen_paths.add(sample_path)
    data = sample_path.read_bytes()
    if len(data) != value_count:
        raise SystemExit(f"size mismatch for {sample_path}: got={len(data)} expected={value_count}")
    if int(row["sample_size_bytes"]) != len(data):
        raise SystemExit(f"index size mismatch for {sample_path}")
    for byte in data:
        histogram[byte] = histogram.get(byte, 0) + 1
    total_values += value_count
    total_bytes += len(data)

if total_values < min_values:
    raise SystemExit(f"only {total_values} values, minimum is {min_values}")
if total_bytes > max_primary_bytes:
    raise SystemExit(f"primary bytes too large: {total_bytes} > {max_primary_bytes}")
if len(histogram) <= 1:
    raise SystemExit(f"constant topic-count stream rejected: {histogram}")

stats_histogram = {int(key): int(value) for key, value in stats.get("histogram", {}).items()}
if stats_histogram != histogram:
    raise SystemExit(f"histogram mismatch: stats={stats_histogram} actual={histogram}")
if int(stats.get("primary_values", -1)) != total_values:
    raise SystemExit(f"stats primary_values mismatch: {stats.get('primary_values')} != {total_values}")
if int(stats.get("primary_sample_bytes", -1)) != total_bytes:
    raise SystemExit(f"stats primary_sample_bytes mismatch: {stats.get('primary_sample_bytes')} != {total_bytes}")

print(
    f"verified_samples={len(rows)} primary_values={total_values} primary_bytes={total_bytes} "
    f"histogram={dict(sorted(histogram.items()))}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
