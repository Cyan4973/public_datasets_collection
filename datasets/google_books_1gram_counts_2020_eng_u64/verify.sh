#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_books_1gram_counts_2020_eng_u64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR"

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
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
filter_dir = Path(os.environ["FILTER_DIR"])
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = filter_dir / "ingest_stats.json"

if not index_path.is_file():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.is_file():
    raise SystemExit(f"missing stats: {stats_path}")

rows = []
seen = set()
total_bytes = 0
total_values = 0
for line in index_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("dataset_id") != "google_books_1gram_counts_2020_eng_u64":
        raise SystemExit(f"wrong dataset_id: {row.get('dataset_id')}")
    if row.get("family") != "google_books_1gram_yearly_counts":
        raise SystemExit(f"wrong family: {row.get('family')}")
    if row.get("role") != "primary":
        raise SystemExit(f"unexpected role: {row.get('role')}")
    if row.get("endianness") != "little":
        raise SystemExit(f"unexpected endianness: {row.get('endianness')}")
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {path}")
    size = path.stat().st_size
    if size != row["sample_size_bytes"]:
        raise SystemExit(f"size mismatch for {path}: {size} != {row['sample_size_bytes']}")
    if size % row["element_size_bytes"] != 0:
        raise SystemExit(f"alignment mismatch: {path}")
    if size // row["element_size_bytes"] != row["value_count"]:
        raise SystemExit(f"value count mismatch: {path}")
    seen.add(row["series_id"])
    total_bytes += size
    total_values += int(row["value_count"])
    rows.append(row)

expected = {
    "google_books_1gram_year_u16",
    "google_books_1gram_match_count_u64",
    "google_books_1gram_volume_count_u64",
}
if seen != expected:
    raise SystemExit(f"unexpected series set: {sorted(seen)}")
stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats["observations"] < 20_000_000:
    raise SystemExit(f"too few observations: {stats['observations']}")
if total_values < 60_000_000:
    raise SystemExit(f"too few total values: {total_values}")
if total_bytes < 400_000_000:
    raise SystemExit(f"too few primary bytes: {total_bytes}")
if total_bytes > 1_000_000_000:
    raise SystemExit(f"primary bytes exceed 1 GB cap: {total_bytes}")
if stats["samples"] != len(rows):
    raise SystemExit(f"stats/index sample mismatch: {stats['samples']} != {len(rows)}")
if stats["primary_values"] != total_values:
    raise SystemExit(f"stats/index value mismatch: {stats['primary_values']} != {total_values}")
if stats["primary_sample_bytes"] != total_bytes:
    raise SystemExit(f"stats/index byte mismatch: {stats['primary_sample_bytes']} != {total_bytes}")
if not (1400 <= stats["min_year"] <= stats["max_year"] <= 2100):
    raise SystemExit(f"unexpected year range: {stats['min_year']}..{stats['max_year']}")

print(
    f"verified dataset=google_books_1gram_counts_2020_eng_u64 samples={len(rows)} "
    f"observations={stats['observations']} values={total_values} bytes={total_bytes}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
