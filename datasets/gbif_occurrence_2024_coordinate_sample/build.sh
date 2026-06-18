#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gbif_occurrence_2024_coordinate_sample"
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
import math
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

pages = sorted(download_dir.glob("gbif_occurrence_2024_jan_offset_*.json"))
if not pages:
    raise SystemExit(f"missing GBIF JSON pages under {download_dir}")

for path in (filter_dir, index_dir, samples_dir):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

records_by_key: dict[int, dict] = {}
raw_rows = 0
for page in pages:
    obj = json.load(open(page, encoding="utf-8"))
    results = obj.get("results")
    if not isinstance(results, list):
        raise SystemExit(f"{page}: missing results")
    raw_rows += len(results)
    for row in results:
        try:
            key = int(row["key"])
        except Exception:
            continue
        records_by_key.setdefault(key, row)

records = []
skipped = 0
for key, row in records_by_key.items():
    try:
        taxon_key = int(row["taxonKey"])
        kingdom_key = int(row["kingdomKey"])
        phylum_key = int(row["phylumKey"])
        class_key = int(row["classKey"])
        order_key = int(row["orderKey"])
        lat = float(row["decimalLatitude"])
        lon = float(row["decimalLongitude"])
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError("non-finite coordinate")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ValueError("coordinate out of range")
    except Exception:
        skipped += 1
        continue
    records.append((key, taxon_key, kingdom_key, phylum_key, class_key, order_key, lat, lon))

records.sort(key=lambda item: item[0])

series = {
    "gbif_occurrence_key_u64": ("uint", 64, "Q", [item[0] for item in records]),
    "gbif_taxon_key_u32": ("uint", 32, "I", [item[1] for item in records]),
    "gbif_kingdom_key_u32": ("uint", 32, "I", [item[2] for item in records]),
    "gbif_phylum_key_u32": ("uint", 32, "I", [item[3] for item in records]),
    "gbif_class_key_u32": ("uint", 32, "I", [item[4] for item in records]),
    "gbif_order_key_u32": ("uint", 32, "I", [item[5] for item in records]),
    "gbif_decimal_latitude_f64": ("float", 64, "d", [item[6] for item in records]),
    "gbif_decimal_longitude_f64": ("float", 64, "d", [item[7] for item in records]),
}

rows = []
for series_id, (kind, bits, code, values) in series.items():
    if not values:
        continue
    series_dir = samples_dir / series_id
    series_dir.mkdir(parents=True, exist_ok=True)
    out = series_dir / f"{series_id}_n{len(values):08d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append(
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
            "value_count": len(values),
            "sample_geometry": "gbif_occurrence_table_column",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["occurrence"],
            "source_name": "gbif_occurrence_2024_01",
            "event_date_window": "2024-01-01..2024-01-31",
            "has_coordinate": True,
        }
    )

counts = [int(row["value_count"]) for row in rows]
sizes = [int(row["sample_size_bytes"]) for row in rows]
stats = {
    "dataset_id": dataset_id,
    "downloaded_pages": len(pages),
    "raw_rows": raw_rows,
    "unique_occurrences": len(records_by_key),
    "rows_skipped": skipped,
    "retained_rows": len(records),
    "primary_samples": len(rows),
    "primary_values": sum(counts),
    "primary_bytes": sum(sizes),
    "median_primary_values": statistics.median(counts) if counts else 0,
    "source_bytes": sum(path.stat().st_size for path in pages),
}
if stats["primary_values"] < 10_000:
    raise SystemExit(f"primary values below floor: {stats['primary_values']}")
if stats["median_primary_values"] < 1_000:
    raise SystemExit(f"median primary sample values below floor: {stats['median_primary_values']}")
if stats["retained_rows"] < 10_000:
    raise SystemExit(f"retained rows below expected bounded sample floor: {stats['retained_rows']}")

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={len(rows)} primary_values={stats['primary_values']} "
    f"primary_bytes={stats['primary_bytes']} median_values={stats['median_primary_values']} "
    f"retained_rows={stats['retained_rows']}"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
