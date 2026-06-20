#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="jpl_cad_2024"
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

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

obj = json.load(open(download_dir / "cad_2024.json", encoding="utf-8"))
field_index = {name: i for i, name in enumerate(obj["fields"])}

# series_id -> CAD field name (all native float64)
defs = {
    "jpl_cad_jd": "jd",
    "jpl_cad_dist": "dist",
    "jpl_cad_dist_min": "dist_min",
    "jpl_cad_dist_max": "dist_max",
    "jpl_cad_v_rel": "v_rel",
    "jpl_cad_v_inf": "v_inf",
    "jpl_cad_h": "h",
}
vals: dict[str, list] = {sid: [] for sid in defs}
if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
for sid in defs:
    (samples_dir / sid).mkdir(parents=True, exist_ok=True)

rows_total = 0
rows_skipped = 0
for row in obj["data"]:
    rows_total += 1
    before = len(vals["jpl_cad_jd"])
    try:
        parsed = {sid: float(row[field_index[field]]) for sid, field in defs.items()}
        for sid in defs:
            vals[sid].append(parsed[sid])
    except Exception:
        for series_values in vals.values():
            while len(series_values) > before:
                series_values.pop()
        rows_skipped += 1

kept_rows = len(vals["jpl_cad_jd"])
if len({len(series_values) for series_values in vals.values()}) != 1:
    raise SystemExit("series length mismatch after filtering")
if kept_rows == 0:
    raise SystemExit("no rows kept")

rows = []
for sid in defs:
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_f64_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + "d" * len(values), *values))
    rows.append(
        {
            "dataset_id": "jpl_cad_2024",
            "series_id": sid,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_geometry": "table_column",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "table_row_count": kept_rows,
            "table_column_count": len(defs),
            "natural_record_kind": "jpl_close_approach_row",
            "natural_record_count": kept_rows,
            "natural_record_values": len(defs),
        }
    )

primary_bytes = sum(row["sample_size_bytes"] for row in rows)
primary_values = sum(row["value_count"] for row in rows)
stats = {
    "dataset_id": "jpl_cad_2024",
    "rows_total": rows_total,
    "rows_skipped": rows_skipped,
    "rows_kept": kept_rows,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built rows_kept={kept_rows} rows_skipped={rows_skipped} primary_values={primary_values} primary_bytes={primary_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
