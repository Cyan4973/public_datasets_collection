#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="hyg_star_photometry_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
FILTER_DIR="$DATA_ROOT/filtered/$DATASET_ID"
INDEX_DIR="$DATA_ROOT/index/$DATASET_ID"
SAMPLES_DIR="$DATA_ROOT/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export DATA_ROOT DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "hyg_star_photometry_i16"
SCALE = int(os.environ.get("HYG_MMAG_SCALE", "1000"))   # magnitudes -> millimagnitudes
I16_MIN, I16_MAX = -32768, 32767
MIN_VALUES_PER_SAMPLE = int(os.environ.get("HYG_MIN_VALUES_PER_SAMPLE", "10000"))
MIN_SAMPLE_COUNT = int(os.environ.get("HYG_MIN_SAMPLE_COUNT", "3"))
MAX_PRIMARY_BYTES = int(os.environ.get("HYG_MAX_PRIMARY_BYTES", "1000000000"))

data_root = Path(os.environ["DATA_ROOT"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

# series_id -> (csv_column, description)
SERIES = {
    "hyg_star_apparent_mag_mmag_i16": ("mag", "Apparent visual magnitude"),
    "hyg_star_absolute_mag_mmag_i16": ("absmag", "Absolute visual magnitude"),
    "hyg_star_color_index_mmag_i16": ("ci", "Johnson B-V colour index"),
}

src = download_dir / "hyg.csv"
if not src.exists():
    raise SystemExit(f"missing source CSV: {src}; run download.sh first")

shutil.rmtree(samples_dir, ignore_errors=True)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

vals: dict[str, list[int]] = {sid: [] for sid in SERIES}
rows_total = 0
skips: dict[str, int] = {}
with src.open("r", encoding="utf-8", newline="") as fh:
    reader = csv.DictReader(fh)
    have = {c.strip().lower(): c for c in (reader.fieldnames or [])}
    for sid, (col, _desc) in SERIES.items():
        if col not in have:
            raise SystemExit(f"source CSV missing column '{col}' for {sid}")
    for row in reader:
        rows_total += 1
        for sid, (col, _desc) in SERIES.items():
            raw = (row.get(have[col]) or "").strip()
            if raw == "":
                skips[f"{sid}:blank"] = skips.get(f"{sid}:blank", 0) + 1
                continue
            try:
                scaled = round(float(raw) * SCALE)
            except ValueError:
                skips[f"{sid}:unparseable"] = skips.get(f"{sid}:unparseable", 0) + 1
                continue
            if not (I16_MIN <= scaled <= I16_MAX):
                skips[f"{sid}:out_of_range"] = skips.get(f"{sid}:out_of_range", 0) + 1
                continue
            vals[sid].append(scaled)

rows = []
total_primary_bytes = 0
for sid, (col, desc) in SERIES.items():
    values = vals[sid]
    if len(values) < MIN_VALUES_PER_SAMPLE:
        raise SystemExit(f"{sid}: only {len(values)} values (< {MIN_VALUES_PER_SAMPLE})")
    if len(set(values)) <= 1:
        raise SystemExit(f"{sid}: constant sample")
    out = samples_dir / sid / f"{sid}.bin"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(struct.pack("<" + "h" * len(values), *values))
    size = out.stat().st_size
    total_primary_bytes += size
    if total_primary_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary output exceeds cap: {total_primary_bytes}")
    rows.append({
        "dataset_id": DATASET_ID,
        "series_id": sid,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "int",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": size,
        "value_count": len(values),
        "min": min(values),
        "max": max(values),
        "sample_geometry": "1d_sequence",
        "sample_rank": 1,
        "sample_axes": ["star"],
        "natural_record_kind": "hyg_catalog_column",
        "source_column": col,
        "scale": SCALE,
    })

if len(rows) < MIN_SAMPLE_COUNT:
    raise SystemExit(f"only {len(rows)} series produced (< {MIN_SAMPLE_COUNT})")

stats = {
    "dataset_id": DATASET_ID,
    "rows_total": rows_total,
    "scale": SCALE,
    "series": {r["series_id"]: {"value_count": r["value_count"], "min": r["min"], "max": r["max"]} for r in rows},
    "skips": skips,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")

print(
    f"built rows_total={rows_total} series={len(rows)} "
    f"values={[r['value_count'] for r in rows]} bytes={total_primary_bytes}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
