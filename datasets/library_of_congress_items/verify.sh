#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="library_of_congress_items"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

export REPO_ROOT DATA_DIR DATASET_ID FILTER_DIR INDEX_DIR
python3 - <<'PY'
import json
import os
import statistics
import struct
from pathlib import Path

root = Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
dataset_id = os.environ["DATASET_ID"]
rows=[json.loads(line) for line in (Path(os.environ["INDEX_DIR"])/"samples.jsonl").read_text().splitlines() if line.strip()]
stats=json.loads((Path(os.environ["FILTER_DIR"])/"ingest_stats.json").read_text())
allowed = {
    "loc_extract_timestamp_u32": ("primary", "uint", 32, 4, "I"),
    "loc_numeric_shelf_id_u64": ("primary", "uint", 64, 8, "Q"),
    "loc_resource_files_sum_u32": ("primary", "uint", 32, 4, "I"),
    "loc_resource_segments_sum_u32": ("primary", "uint", 32, 4, "I"),
    "loc_item_date_year_u16": ("primary", "uint", 16, 2, "H"),
}
if stats.get("dataset_id") != dataset_id:
    raise SystemExit("stats dataset mismatch")
if len(rows) != len(allowed):
    raise SystemExit(f"unexpected sample row count {len(rows)}")

counts = []
sizes = []
for row in rows:
    sid = row["series_id"]
    if sid not in allowed:
        raise SystemExit(f"unexpected series: {sid}")
    role, kind, bits, elem, code = allowed[sid]
    if row.get("role") != role or row.get("numeric_kind") != kind or int(row["bit_width"]) != bits:
        raise SystemExit(f"bad metadata for {sid}: {row}")
    path = root / row["sample_path"]
    if not path.is_file():
        raise SystemExit(f"missing sample {row['sample_path']}")
    count = int(row["value_count"])
    size = int(row["sample_size_bytes"])
    if count <= 0:
        raise SystemExit(f"empty sample {row['sample_path']}")
    if size != count * elem or path.stat().st_size != size:
        raise SystemExit(f"size/count mismatch {row['sample_path']}")
    data = path.read_bytes()
    if len(data) != size:
        raise SystemExit(f"read size mismatch {row['sample_path']}")
    values = struct.unpack("<" + code * count, data)
    if count > 1 and len(set(values)) <= 1:
        raise SystemExit(f"globally constant sample rejected: {row['sample_path']}")
    counts.append(count)
    sizes.append(size)

primary_values = sum(counts)
primary_bytes = sum(sizes)
median_values = statistics.median(counts)
if primary_values != int(stats["primary_values"]) or primary_bytes != int(stats["primary_bytes"]):
    raise SystemExit("stats/index primary totals mismatch")
if int(stats["rows_total"]) < 10_000:
    raise SystemExit(f"LOC records below repair floor: {stats['rows_total']}")
if primary_values < 10_000:
    raise SystemExit(f"primary values below floor: {primary_values}")
if primary_bytes < 100 * 1024:
    raise SystemExit(f"primary bytes below floor: {primary_bytes}")
if median_values < 1_000:
    raise SystemExit(f"median primary sample values below floor: {median_values}")

print(
    f"verified_samples={len(rows)} rows_total={stats['rows_total']} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_values={median_values}"
)
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
