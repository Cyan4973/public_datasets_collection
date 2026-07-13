#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bam_read_mapq_u8"
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
from array import array
from pathlib import Path

DATASET_ID = "bam_read_mapq_u8"
SERIES_ID = "bam_read_mapq_u8"
MIN_PRIMARY_VALUES = int(os.environ.get("BAM_MIN_PRIMARY_VALUES", "100000"))
MIN_PRIMARY_BYTES = int(os.environ.get("BAM_MIN_PRIMARY_BYTES", str(100 * 1024)))
MIN_MEDIAN_VALUES = int(os.environ.get("BAM_MIN_MEDIAN_VALUES", "10000"))
MIN_SAMPLE_COUNT = int(os.environ.get("BAM_MIN_SAMPLE_COUNT", "5"))
MAX_PRIMARY_BYTES = int(os.environ.get("BAM_MAX_PRIMARY_BYTES", "1000000000"))

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if len(rows) < MIN_SAMPLE_COUNT:
    raise SystemExit(f"expected at least {MIN_SAMPLE_COUNT} BAM MAPQ samples, found {len(rows)}")

sizes = []
values = []
for row in rows:
    if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
        raise SystemExit(f"unexpected row identity: {row}")
    if row.get("numeric_kind") != "uint" or int(row.get("bit_width", 0)) != 8 or int(row.get("element_size_bytes", 0)) != 1:
        raise SystemExit(f"unexpected numeric representation: {row}")
    if row.get("sample_geometry") != "1d_sequence" or int(row.get("sample_rank", 0)) != 1:
        raise SystemExit(f"unexpected geometry: {row}")
    if row.get("natural_record_kind") != "bam_read_mapq_stream":
        raise SystemExit(f"unexpected natural boundary: {row}")
    path = data_root / row["sample_path"]
    expected_bytes = int(row["sample_size_bytes"])
    expected_values = int(row["value_count"])
    if expected_bytes != expected_values:
        raise SystemExit(f"uint8 byte/value mismatch: {path}")
    if not path.is_file() or path.stat().st_size != expected_bytes:
        raise SystemExit(f"size mismatch: {path}")
    data = path.read_bytes()
    sample = min(len(data), 200_000)
    vals = array("B")
    vals.frombytes(data[:sample])
    if vals.count(vals[0]) == len(vals):
        raise SystemExit(f"constant prefix rejected: {path}")
    # uint8 range is guaranteed by construction; cross-check declared stats.
    if int(row.get("mapq_min", 0)) < 0 or int(row.get("mapq_max", 0)) > 255:
        raise SystemExit(f"mapq outside uint8 range: {row}")
    sizes.append(expected_bytes)
    values.append(expected_values)

primary_bytes = sum(sizes)
primary_values = sum(values)
if primary_values < MIN_PRIMARY_VALUES:
    raise SystemExit(f"primary_values below floor: {primary_values}")
if primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary_bytes below floor: {primary_bytes}")
if statistics.median(values) < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {int(statistics.median(values))}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary_bytes exceeds cap: {primary_bytes}")
if primary_bytes != int(stats.get("total_primary_bytes", -1)):
    raise SystemExit("stats/index primary byte mismatch")

print(
    f"verified_rows={len(rows)} primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_values={int(statistics.median(values))} size_range={min(sizes)}/{int(statistics.median(sizes))}/{max(sizes)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
