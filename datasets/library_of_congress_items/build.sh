#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="library_of_congress_items"
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

export REPO_ROOT DATA_DIR DATASET_ID DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import calendar
import json
import os
import re
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

for path in (filter_dir, index_dir, samples_dir):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

page_files = sorted(download_dir.glob("items_page_*.json"))
if not page_files and (download_dir / "items.json").exists():
    page_files = [download_dir / "items.json"]
if not page_files:
    raise SystemExit("missing LOC item JSON pages; run download.sh first")
inventory_path = download_dir / "download_inventory.json"
if inventory_path.exists() and page_files[0].name.startswith("items_page_"):
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    expected_page_count = int(inventory.get("requested_page_count") or os.environ.get("LOC_PAGE_COUNT", "150"))
    expected_pages = set(range(1, expected_page_count + 1))
    found_pages = {
        int(path.stem.rsplit("_", 1)[1])
        for path in page_files
        if path.stem.rsplit("_", 1)[1].isdigit()
    }
    missing_pages = sorted(expected_pages - found_pages)
    if missing_pages:
        raise SystemExit(f"incomplete LOC page range; missing pages: {missing_pages}")

series = {
    "loc_extract_timestamp_u32": ("uint", 32, "I", 0, 2**32 - 1),
    "loc_numeric_shelf_id_u64": ("uint", 64, "Q", 0, 2**64 - 1),
    "loc_resource_files_sum_u32": ("uint", 32, "I", 0, 2**32 - 1),
    "loc_resource_segments_sum_u32": ("uint", 32, "I", 0, 2**32 - 1),
    "loc_item_date_year_u16": ("uint", 16, "H", 0, 65535),
}
values = {sid: [] for sid in series}
missing = {sid: 0 for sid in series}
rows_total = 0

def parse_timestamp(text: str) -> int | None:
    if not text:
        return None
    try:
        return calendar.timegm(datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").utctimetuple())
    except ValueError:
        return None

def parse_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def parse_year(row: dict) -> int | None:
    candidates = [row.get("date")]
    item = row.get("item")
    if isinstance(item, dict):
        candidates.extend([item.get("date"), item.get("date_issued"), item.get("sort_date")])
    for candidate in candidates:
        if not candidate:
            continue
        match = re.search(r"\b(\d{4})\b", str(candidate))
        if not match:
            continue
        year = int(match.group(1))
        if 0 <= year <= 3000:
            return year
    return None

for page_path in page_files:
    obj = json.load(open(page_path, encoding="utf-8"))
    results = obj.get("results")
    if not isinstance(results, list):
        raise SystemExit(f"{page_path.name}: missing results list")
    for row in results:
        if not isinstance(row, dict):
            continue
        rows_total += 1
        resources = row.get("resources") or []
        if not isinstance(resources, list):
            resources = []

        parsed = {
            "loc_extract_timestamp_u32": parse_timestamp(str(row.get("extract_timestamp") or "")),
            "loc_numeric_shelf_id_u64": parse_int(row.get("numeric_shelf_id")),
            "loc_resource_files_sum_u32": sum(
                parse_int(resource.get("files")) or 0
                for resource in resources
                if isinstance(resource, dict)
            ),
            "loc_resource_segments_sum_u32": sum(
                parse_int(resource.get("segments")) or 0
                for resource in resources
                if isinstance(resource, dict)
            ),
            "loc_item_date_year_u16": parse_year(row),
        }
        for sid, value in parsed.items():
            kind, bits, code, min_value, max_value = series[sid]
            if value is None:
                missing[sid] += 1
                continue
            if value < min_value or value > max_value:
                raise SystemExit(f"{page_path.name}: {sid} value {value} outside range")
            values[sid].append(value)

sample_rows = []
for sid, vals in values.items():
    kind, bits, code, min_value, max_value = series[sid]
    if not vals:
        continue
    out = samples_dir / sid / f"{sid}_n{len(vals):08d}.bin"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(vals), *vals))
    sample_rows.append(
        {
            "dataset_id": dataset_id,
            "series_id": sid,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(vals),
            "sample_geometry": "loc_item_result_field",
            "sample_rank": 1,
            "sample_shape": [len(vals)],
            "sample_axes": ["catalog_result"],
        }
    )

primary_counts = [int(row["value_count"]) for row in sample_rows]
primary_sizes = [int(row["sample_size_bytes"]) for row in sample_rows]
stats = {
    "dataset_id": dataset_id,
    "page_files": len(page_files),
    "rows_total": rows_total,
    "missing_by_series": missing,
    "kept_by_series": {sid: len(vals) for sid, vals in values.items()},
    "primary_samples": len(sample_rows),
    "primary_values": sum(primary_counts),
    "primary_bytes": sum(primary_sizes),
    "median_primary_values": statistics.median(primary_counts) if primary_counts else 0,
    "min_primary_values": min(primary_counts) if primary_counts else 0,
    "max_primary_values": max(primary_counts) if primary_counts else 0,
    "source_bytes": sum(path.stat().st_size for path in page_files),
}
if stats["rows_total"] < 10_000:
    raise SystemExit(f"LOC records below repair floor: {stats['rows_total']}")
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
with (index_dir/"samples.jsonl").open("w",encoding='utf-8') as fh:
    for row in sample_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={stats['primary_samples']} rows_total={stats['rows_total']} "
    f"primary_values={stats['primary_values']} primary_bytes={stats['primary_bytes']} "
    f"median_values={stats['median_primary_values']} source_bytes={stats['source_bytes']}"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
