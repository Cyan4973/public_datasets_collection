#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gutendex_catalog_books"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DATASET_ID FILTER_DIR INDEX_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
from array import array
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
dataset_id = os.environ["DATASET_ID"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads(stats_path.read_text(encoding="utf-8"))
allowed = {
    "gutendex_download_count_u32": ("primary", "uint", 32, 4, "I"),
    "gutendex_author_birth_year_i16": ("primary", "int", 16, 2, "h"),
    "gutendex_author_death_year_i16": ("primary", "int", 16, 2, "h"),
    "gutendex_book_id_u32": ("auxiliary", "uint", 32, 4, "I"),
}
if stats.get("dataset_id") != dataset_id:
    raise SystemExit("stats dataset mismatch")
if len(rows) != len(allowed):
    raise SystemExit(f"unexpected sample row count: {len(rows)}")

primary_counts = []
primary_sizes = []
for row in rows:
    sid = row["series_id"]
    if sid not in allowed:
        raise SystemExit(f"unexpected series: {sid}")
    role, kind, width, elem, code = allowed[sid]
    if row.get("role") != role or row["numeric_kind"] != kind or int(row["bit_width"]) != width:
        raise SystemExit(f"unexpected row metadata: {row}")
    path = data_root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    count = int(row["value_count"])
    size = int(row["sample_size_bytes"])
    if size != count * elem or path.stat().st_size != size:
        raise SystemExit(f"size/count mismatch: {row['sample_path']}")
    values = array(code)
    with path.open("rb") as fh:
        values.frombytes(fh.read())
    if len(values) != count:
        raise SystemExit(f"decoded value count mismatch: {row['sample_path']}")
    if len(values) > 1 and len(set(values)) <= 1:
        raise SystemExit(f"globally constant sample rejected: {row['sample_path']}")
    if role == "primary":
        primary_counts.append(count)
        primary_sizes.append(size)

primary_values = sum(primary_counts)
primary_bytes = sum(primary_sizes)
median_values = statistics.median(primary_counts)
if primary_values != int(stats["primary_values"]) or primary_bytes != int(stats["primary_bytes"]):
    raise SystemExit("stats/index primary total mismatch")
if primary_values < 10_000:
    raise SystemExit(f"primary values below floor: {primary_values}")
if primary_bytes < 100 * 1024:
    raise SystemExit(f"primary bytes below floor: {primary_bytes}")
if median_values < 1_000:
    raise SystemExit(f"median primary sample values below floor: {median_values}")

print(
    f"verified_samples={len(rows)} primary_values={primary_values} "
    f"primary_bytes={primary_bytes} median_values={median_values} "
    f"retained_books={stats.get('retained_books')} retained_author_records={stats.get('retained_author_records')}"
)
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
