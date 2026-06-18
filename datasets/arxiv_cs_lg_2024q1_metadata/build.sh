#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="arxiv_cs_lg_2024q1_metadata"
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
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
dataset_id = os.environ["DATASET_ID"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

pages = sorted(download_dir.glob("arxiv_cs_lg_2024q1_start_*.xml"))
if not pages:
    raise SystemExit(f"missing arXiv XML pages under {download_dir}")

for path in (filter_dir, index_dir, samples_dir):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

def child_text(elem: ET.Element, suffix: str) -> str:
    for child in elem:
        if child.tag.endswith(suffix):
            return (child.text or "").strip()
    return ""

def parse_ts(text: str) -> int:
    return calendar.timegm(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").utctimetuple())

entries_by_id: dict[str, ET.Element] = {}
raw_entries = 0
for page in pages:
    root = ET.parse(page).getroot()
    for entry in (elem for elem in root.iter() if elem.tag.endswith("entry")):
        raw_entries += 1
        entry_id = child_text(entry, "id")
        if entry_id:
            entries_by_id.setdefault(entry_id, entry)

records = []
skipped = 0
for entry_id, entry in entries_by_id.items():
    try:
        published = parse_ts(child_text(entry, "published"))
        updated = parse_ts(child_text(entry, "updated"))
        author_count = sum(1 for child in entry if child.tag.endswith("author"))
        category_count = sum(1 for child in entry if child.tag.endswith("category"))
        if author_count <= 0 or category_count <= 0:
            raise ValueError("missing authors or categories")
    except Exception:
        skipped += 1
        continue
    records.append((published, entry_id, updated, author_count, category_count))

records.sort(key=lambda item: (item[0], item[1]))

series = {
    "arxiv_cs_lg_published_at_u32": ("uint", 32, "I", [item[0] for item in records]),
    "arxiv_cs_lg_updated_at_u32": ("uint", 32, "I", [item[2] for item in records]),
    "arxiv_cs_lg_author_count_u16": ("uint", 16, "H", [item[3] for item in records]),
    "arxiv_cs_lg_category_count_u16": ("uint", 16, "H", [item[4] for item in records]),
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
            "sample_geometry": "arxiv_metadata_table_column",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["entry"],
            "source_name": "arxiv_cs_lg_2024q1",
            "arxiv_category": "cs.LG",
            "submitted_date_window": "202401010000..202403312359",
        }
    )

counts = [int(row["value_count"]) for row in rows]
sizes = [int(row["sample_size_bytes"]) for row in rows]
stats = {
    "dataset_id": dataset_id,
    "downloaded_pages": len(pages),
    "raw_entries": raw_entries,
    "unique_entries": len(entries_by_id),
    "rows_skipped": skipped,
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

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={len(rows)} primary_values={stats['primary_values']} "
    f"primary_bytes={stats['primary_bytes']} median_values={stats['median_primary_values']} "
    f"unique_entries={stats['unique_entries']}"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
