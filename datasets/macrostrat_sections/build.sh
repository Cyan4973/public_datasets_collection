#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="macrostrat_sections"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DATASET_ID DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import statistics
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
dataset_id = os.environ["DATASET_ID"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

src = json.loads((download_dir / "macrostrat_sections.json").read_text(encoding="utf-8"))
rows_src = src["success"]["data"]

for path in (filter_dir, index_dir, samples_dir):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

spec = {
    "macrostrat_section_t_age_f32": ("t_age", "float", 32, "f"),
    "macrostrat_section_b_age_f32": ("b_age", "float", 32, "f"),
    "macrostrat_section_area_f32": ("col_area", "float", 32, "f"),
    "macrostrat_section_max_thick_f32": ("max_thick", "float", 32, "f"),
    "macrostrat_section_min_thick_f32": ("min_thick", "float", 32, "f"),
    "macrostrat_section_pbdb_collections_u32": ("pbdb_collections", "uint", 32, "I"),
}
values = {series_id: [] for series_id in spec}
skipped = {series_id: 0 for series_id in spec}

for row in rows_src:
    for series_id, (source_field, kind, bits, code) in spec.items():
        raw_value = row.get(source_field)
        try:
            if kind == "uint":
                value = int(raw_value)
                if not 0 <= value <= 0xFFFFFFFF:
                    raise ValueError("uint32 range")
            else:
                value = float(raw_value)
            values[series_id].append(value)
        except Exception:
            skipped[series_id] += 1

sample_rows = []
for series_id, (source_field, kind, bits, code) in spec.items():
    vals = values[series_id]
    out = samples_dir / series_id / f"{series_id}_n{len(vals):08d}.bin"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(vals), *vals))
    sample_rows.append(
        {
            "dataset_id": dataset_id,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(vals),
            "sample_geometry": "macrostrat_section_table_field",
            "sample_rank": 1,
            "sample_shape": [len(vals)],
            "sample_axes": ["section"],
            "source_name": "macrostrat_sections_response_long",
        }
    )

counts = [int(row["value_count"]) for row in sample_rows]
sizes = [int(row["sample_size_bytes"]) for row in sample_rows]
stats = {
    "dataset_id": dataset_id,
    "rows_total": len(rows_src),
    "rows_skipped_by_series": skipped,
    "primary_samples": len(sample_rows),
    "primary_values": sum(counts),
    "primary_bytes": sum(sizes),
    "median_primary_values": statistics.median(counts),
    "min_primary_values": min(counts),
    "max_primary_values": max(counts),
    "source_bytes": (download_dir / "macrostrat_sections.json").stat().st_size,
}
if stats["primary_values"] < 10_000:
    raise SystemExit(f"primary values below floor: {stats['primary_values']}")
if stats["primary_bytes"] < 100 * 1024:
    raise SystemExit(f"primary bytes below floor: {stats['primary_bytes']}")
if stats["median_primary_values"] < 1_000:
    raise SystemExit(f"median primary sample values below floor: {stats['median_primary_values']}")

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={len(sample_rows)} primary_values={stats['primary_values']} "
    f"primary_bytes={stats['primary_bytes']} median_values={stats['median_primary_values']} "
    f"source_bytes={stats['source_bytes']}"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
