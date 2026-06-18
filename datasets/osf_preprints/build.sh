#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="osf_preprints"
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

import calendar
import json
import os
import shutil
import statistics
import struct
from datetime import datetime
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
dataset_id = os.environ["DATASET_ID"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

page_files = sorted(download_dir.glob("osf_preprints_page_*.json"))
legacy_file = download_dir / "osf_preprints.json"
if not page_files and legacy_file.exists():
    page_files = [legacy_file]
if not page_files:
    raise SystemExit(f"missing OSF JSON pages under {download_dir}; run download.sh first")

for path in (filter_dir, index_dir, samples_dir):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

def parse_timestamp(value: object) -> int | None:
    if not value:
        return None
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return calendar.timegm(dt.timetuple())
    return int(dt.timestamp())

series = {
    "osf_created_unix_u32": ("uint", 32, "I"),
    "osf_modified_unix_u32": ("uint", 32, "I"),
    "osf_published_unix_u32": ("uint", 32, "I"),
}
values = {sid: [] for sid in series}
rows_total = 0
rows_skipped = 0
raw_ids_seen: set[str] = set()
duplicate_ids = 0
missing_ids = 0

for page_path in page_files:
    obj = json.loads(page_path.read_text(encoding="utf-8"))
    data = obj.get("data")
    if not isinstance(data, list):
        raise SystemExit(f"{page_path.name}: missing data list")
    for row in data:
        if not isinstance(row, dict):
            rows_skipped += 1
            continue
        rows_total += 1
        row_id = str(row.get("id") or "")
        if row_id:
            if row_id in raw_ids_seen:
                duplicate_ids += 1
                continue
            raw_ids_seen.add(row_id)
        else:
            missing_ids += 1
        attrs = row.get("attributes")
        if not isinstance(attrs, dict):
            rows_skipped += 1
            continue
        created = parse_timestamp(attrs.get("date_created"))
        modified = parse_timestamp(attrs.get("date_modified"))
        published = parse_timestamp(attrs.get("date_published"))
        if created is None or modified is None or published is None:
            rows_skipped += 1
            continue
        for value in (created, modified, published):
            if not 0 <= value <= 0xFFFFFFFF:
                raise SystemExit(f"{page_path.name}: timestamp outside uint32 range")
        values["osf_created_unix_u32"].append(created)
        values["osf_modified_unix_u32"].append(modified)
        values["osf_published_unix_u32"].append(published)

sample_rows = []
for series_id, (kind, bits, code) in series.items():
    vals = values[series_id]
    if not vals:
        continue
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
            "sample_geometry": "osf_preprint_record_timestamp_field",
            "sample_rank": 1,
            "sample_shape": [len(vals)],
            "sample_axes": ["preprint_record"],
            "source_name": "osf_preprints_paginated",
        }
    )

primary_counts = [int(row["value_count"]) for row in sample_rows if row["role"] == "primary"]
primary_sizes = [int(row["sample_size_bytes"]) for row in sample_rows if row["role"] == "primary"]
stats = {
    "dataset_id": dataset_id,
    "page_files": len(page_files),
    "rows_total": rows_total,
    "unique_ids": len(raw_ids_seen),
    "duplicate_ids": duplicate_ids,
    "missing_ids": missing_ids,
    "rows_skipped": rows_skipped,
    "complete_timestamp_records": len(values["osf_created_unix_u32"]),
    "primary_samples": len(primary_counts),
    "primary_values": sum(primary_counts),
    "primary_bytes": sum(primary_sizes),
    "median_primary_values": statistics.median(primary_counts) if primary_counts else 0,
    "min_primary_values": min(primary_counts) if primary_counts else 0,
    "max_primary_values": max(primary_counts) if primary_counts else 0,
    "source_bytes": sum(path.stat().st_size for path in page_files),
}
if stats["complete_timestamp_records"] < 10_000:
    raise SystemExit(f"complete timestamp records below repair floor: {stats['complete_timestamp_records']}")
if stats["primary_values"] < 10_000:
    raise SystemExit(f"primary values below floor: {stats['primary_values']}")
if stats["primary_bytes"] < 100 * 1024:
    raise SystemExit(f"primary bytes below floor: {stats['primary_bytes']}")
if stats["median_primary_values"] < 1_000:
    raise SystemExit(f"median primary sample values below floor: {stats['median_primary_values']}")

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={len(sample_rows)} complete_timestamp_records={stats['complete_timestamp_records']} "
    f"primary_values={stats['primary_values']} primary_bytes={stats['primary_bytes']} "
    f"median_values={stats['median_primary_values']} source_bytes={stats['source_bytes']}"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
