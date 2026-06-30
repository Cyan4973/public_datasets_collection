#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="taginfo_tags_popular"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export TAGINFO_TAGS_MIN_RETAINED_RECORDS="${TAGINFO_TAGS_MIN_RETAINED_RECORDS:-14000}"
export TAGINFO_TAGS_MIN_PRIMARY_VALUES="${TAGINFO_TAGS_MIN_PRIMARY_VALUES:-100000}"
export TAGINFO_TAGS_MIN_PRIMARY_BYTES="${TAGINFO_TAGS_MIN_PRIMARY_BYTES:-102400}"
export TAGINFO_TAGS_MIN_MEDIAN_VALUES="${TAGINFO_TAGS_MIN_MEDIAN_VALUES:-1000}"
python3 - <<'PY' "$REPO_ROOT" "$DATA_DIR" "$FILTER_DIR" "$INDEX_DIR"
from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
data_dir = sys.argv[2]
filter_dir = Path(sys.argv[3])
index_dir = Path(sys.argv[4])
min_retained = int(os.environ["TAGINFO_TAGS_MIN_RETAINED_RECORDS"])
min_primary_values = int(os.environ["TAGINFO_TAGS_MIN_PRIMARY_VALUES"])
min_primary_bytes = int(os.environ["TAGINFO_TAGS_MIN_PRIMARY_BYTES"])
min_median_values = int(os.environ["TAGINFO_TAGS_MIN_MEDIAN_VALUES"])

stats = json.loads((filter_dir / "ingest_stats.json").read_text(encoding="utf-8"))
rows = [json.loads(line) for line in (index_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
expected_roles = {
    "taginfo_tag_count_all": "primary",
    "taginfo_tag_count_all_fraction": "primary",
    "taginfo_tag_count_nodes": "primary",
    "taginfo_tag_count_nodes_fraction": "primary",
    "taginfo_tag_count_ways": "primary",
    "taginfo_tag_count_ways_fraction": "primary",
    "taginfo_tag_count_relations": "primary",
    "taginfo_tag_count_relations_fraction": "primary",
    "taginfo_tag_projects": "auxiliary",
    "taginfo_tag_in_wiki": "auxiliary",
}
series_ids = {row["series_id"] for row in rows}
if series_ids != set(expected_roles):
    raise SystemExit(f"series mismatch: {sorted(series_ids)}")

retained = int(stats["retained_records"])
if retained < min_retained:
    raise SystemExit(f"retained_records below repair floor: {retained} < {min_retained}")
if int(stats["primary_values"]) < min_primary_values:
    raise SystemExit(f"primary_values below repair target: {stats['primary_values']} < {min_primary_values}")
if int(stats["primary_sample_bytes"]) < min_primary_bytes:
    raise SystemExit(f"primary_sample_bytes below floor: {stats['primary_sample_bytes']} < {min_primary_bytes}")

primary_counts = []
primary_bytes = []
for row in rows:
    series_id = row["series_id"]
    role = row.get("role")
    if role != expected_roles[series_id]:
        raise SystemExit(f"{series_id}: expected role {expected_roles[series_id]} got {role}")
    if int(row["value_count"]) != retained:
        raise SystemExit(f"{series_id}: value_count {row['value_count']} != retained_records {retained}")
    if row.get("min") == row.get("max"):
        raise SystemExit(f"{series_id}: constant min/max")
    sample = repo_root / data_dir / row["sample_path"]
    if not sample.is_file():
        raise SystemExit(f"missing sample {row['sample_path']}")
    expected_size = int(row["value_count"]) * int(row["element_size_bytes"])
    actual_size = sample.stat().st_size
    if actual_size != expected_size or actual_size != int(row["sample_size_bytes"]):
        raise SystemExit(f"{series_id}: sample size mismatch")
    if role == "primary":
        primary_counts.append(int(row["value_count"]))
        primary_bytes.append(actual_size)

if statistics.median(primary_counts) < min_median_values:
    raise SystemExit("median primary values below floor")
if sum(primary_counts) != int(stats["primary_values"]):
    raise SystemExit("primary_values statistic mismatch")
if sum(primary_bytes) != int(stats["primary_sample_bytes"]):
    raise SystemExit("primary_sample_bytes statistic mismatch")

print(
    f"verified_samples={len(rows)} retained_records={retained} "
    f"primary_values={sum(primary_counts)} primary_sample_bytes={sum(primary_bytes)}"
)
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
