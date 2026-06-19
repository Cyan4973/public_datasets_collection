#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="macrostrat_columns"
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
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
dataset_id = os.environ["DATASET_ID"]
rows = [json.loads(line) for line in (Path(os.environ["INDEX_DIR"]) / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
stats = json.loads((Path(os.environ["FILTER_DIR"]) / "ingest_stats.json").read_text(encoding="utf-8"))
allowed = {
    "macrostrat_column_t_age_f32": ("float", 32, 4, "f"),
    "macrostrat_column_b_age_f32": ("float", 32, 4, "f"),
    "macrostrat_column_area_f32": ("float", 32, 4, "f"),
    "macrostrat_column_max_thick_f32": ("float", 32, 4, "f"),
    "macrostrat_column_max_min_thick_f32": ("float", 32, 4, "f"),
    "macrostrat_column_min_min_thick_f32": ("float", 32, 4, "f"),
    "macrostrat_column_pbdb_collections_u32": ("uint", 32, 4, "I"),
    "macrostrat_column_section_count_u32": ("uint", 32, 4, "I"),
    "macrostrat_column_unit_count_u32": ("uint", 32, 4, "I"),
}
if stats.get("dataset_id") != dataset_id:
    raise SystemExit("stats dataset mismatch")
if len(rows) != len(allowed):
    raise SystemExit(f"unexpected sample row count: {len(rows)}")
counts = []
sizes = []
for row in rows:
    series_id = row["series_id"]
    if series_id not in allowed:
        raise SystemExit(f"unexpected series: {series_id}")
    kind, bits, elem, code = allowed[series_id]
    if row.get("role") != "primary" or row["numeric_kind"] != kind or int(row["bit_width"]) != bits:
        raise SystemExit(f"bad metadata: {row}")
    sample = data_root / row["sample_path"]
    if not sample.is_file():
        raise SystemExit(f"missing sample: {row['sample_path']}")
    count = int(row["value_count"])
    size = int(row["sample_size_bytes"])
    if count <= 0 or size != count * elem or sample.stat().st_size != size:
        raise SystemExit(f"size/count mismatch: {row['sample_path']}")
    data = sample.read_bytes()
    values = struct.unpack("<" + code * count, data)
    if len(values) > 1 and len(set(values)) <= 1:
        raise SystemExit(f"globally constant sample rejected: {row['sample_path']}")
    counts.append(count)
    sizes.append(size)
primary_values = sum(counts)
primary_bytes = sum(sizes)
median_values = statistics.median(counts)
if primary_values != int(stats["primary_values"]) or primary_bytes != int(stats["primary_bytes"]):
    raise SystemExit("stats/index primary total mismatch")
if primary_values < 10_000 or primary_bytes < 100 * 1024 or median_values < 1_000:
    raise SystemExit("acceptance floor failed")
print(f"verified_samples={len(rows)} primary_values={primary_values} primary_bytes={primary_bytes} median_values={median_values}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
