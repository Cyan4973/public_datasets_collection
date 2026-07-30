#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_ims_snow_ice_cover_u8"
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
from collections import Counter
from pathlib import Path

DATASET_ID = "noaa_ims_snow_ice_cover_u8"
SERIES_ID = "ims_snow_ice_category_u8"
EXPECTED_SAMPLES = 12
EXPECTED_VALUES = 6144 * 6144
ALLOWED = set(range(5))

data_root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.is_file():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
primary = [row for row in rows if row.get("role") == "primary"]
if len(primary) != EXPECTED_SAMPLES:
    raise SystemExit(f"primary sample count={len(primary)} expected={EXPECTED_SAMPLES}")

dates: set[str] = set()
counts: list[int] = []
aggregate = Counter()
for row in primary:
    if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID:
        raise SystemExit(f"wrong dataset/series identity: {row}")
    if row.get("numeric_kind") != "uint" or int(row.get("bit_width", -1)) != 8:
        raise SystemExit(f"wrong numeric type: {row}")
    if row.get("endianness") != "little" or int(row.get("element_size_bytes", -1)) != 1:
        raise SystemExit(f"wrong byte representation: {row}")
    if row.get("source_format") != "gzip_compressed_ims_ascii_grid":
        raise SystemExit(f"wrong source_format: {row.get('source_format')}")
    if row.get("natural_record_kind") != "complete_ims_daily_4km_analysis_grid":
        raise SystemExit(f"wrong natural_record_kind: {row.get('natural_record_kind')}")
    if row.get("sample_shape") != [6144, 6144]:
        raise SystemExit(f"wrong sample shape: {row.get('sample_shape')}")
    date = str(row.get("analysis_date_utc", ""))
    if not date or date in dates:
        raise SystemExit(f"missing or duplicate analysis date: {date}")
    dates.add(date)
    sample = data_root / row["sample_path"]
    if not sample.is_file():
        raise SystemExit(f"missing sample: {sample}")
    data = sample.read_bytes()
    if len(data) != EXPECTED_VALUES:
        raise SystemExit(f"wrong complete-grid size file={sample} bytes={len(data)}")
    if len(data) != int(row["sample_size_bytes"]) or len(data) != int(row["value_count"]):
        raise SystemExit(f"index size mismatch: {sample}")
    unexpected = set(data) - ALLOWED
    if unexpected:
        raise SystemExit(f"unexpected codes file={sample} codes={sorted(unexpected)}")
    if len(set(data)) < 4:
        raise SystemExit(f"degenerate grid file={sample} codes={sorted(set(data))}")
    hist = Counter(data)
    indexed_hist = {int(key): int(value) for key, value in row["category_histogram"].items()}
    if dict(hist) != indexed_hist:
        raise SystemExit(f"histogram/index mismatch: {sample}")
    aggregate.update(hist)
    counts.append(len(data))

total = sum(counts)
if total < 10_000 or total < 100 * 1024:
    raise SystemExit(f"aggregate floor failed: values={total} bytes={total}")
if statistics.median(counts) < 1_000:
    raise SystemExit(f"median natural sample below floor: {statistics.median(counts)}")
if total > 1_000_000_000:
    raise SystemExit(f"primary byte cap exceeded: {total}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if int(stats["samples"]) != EXPECTED_SAMPLES:
    raise SystemExit("stats sample count mismatch")
if int(stats["primary_values"]) != total or int(stats["primary_sample_bytes"]) != total:
    raise SystemExit("stats primary totals mismatch")
stats_hist = {int(key): int(value) for key, value in stats["category_histogram"].items()}
if dict(aggregate) != stats_hist:
    raise SystemExit("stats aggregate histogram mismatch")

print(
    f"verified dataset={DATASET_ID} samples={len(primary)} values={total} "
    f"bytes={total} median={int(statistics.median(counts))} codes={sorted(aggregate)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
