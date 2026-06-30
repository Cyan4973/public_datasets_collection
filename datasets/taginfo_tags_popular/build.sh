#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="taginfo_tags_popular"
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

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export TAGINFO_TAGS_MIN_RETAINED_RECORDS="${TAGINFO_TAGS_MIN_RETAINED_RECORDS:-14000}"
export TAGINFO_TAGS_MIN_PRIMARY_VALUES="${TAGINFO_TAGS_MIN_PRIMARY_VALUES:-100000}"
export TAGINFO_TAGS_MIN_PRIMARY_BYTES="${TAGINFO_TAGS_MIN_PRIMARY_BYTES:-102400}"
export TAGINFO_TAGS_MIN_MEDIAN_VALUES="${TAGINFO_TAGS_MIN_MEDIAN_VALUES:-1000}"
python3 - <<'PY'
from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "taginfo_tags_popular"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_retained = int(os.environ["TAGINFO_TAGS_MIN_RETAINED_RECORDS"])
min_primary_values = int(os.environ["TAGINFO_TAGS_MIN_PRIMARY_VALUES"])
min_primary_bytes = int(os.environ["TAGINFO_TAGS_MIN_PRIMARY_BYTES"])
min_median_values = int(os.environ["TAGINFO_TAGS_MIN_MEDIAN_VALUES"])


def load_source_rows() -> tuple[list[dict], int]:
    tmp_page_files = sorted((download_dir / "pages.tmp").glob("page_*.json"))
    if tmp_page_files:
        rows: list[dict] = []
        for page_file in tmp_page_files:
            obj = json.loads(page_file.read_text(encoding="utf-8"))
            data = obj.get("data")
            if not isinstance(data, list):
                raise SystemExit(f"{page_file}: missing data list")
            rows.extend(data)
        return rows, len(tmp_page_files)

    combined = download_dir / "taginfo_tags_popular.json"
    if combined.is_file():
        obj = json.loads(combined.read_text(encoding="utf-8"))
        data = obj.get("data")
        if isinstance(data, list):
            return data, int((obj.get("download") or {}).get("page_count") or 1)

    page_files = sorted((download_dir / "pages").glob("page_*.json"))
    if page_files:
        rows: list[dict] = []
        for page_file in page_files:
            obj = json.loads(page_file.read_text(encoding="utf-8"))
            data = obj.get("data")
            if not isinstance(data, list):
                raise SystemExit(f"{page_file}: missing data list")
            rows.extend(data)
        return rows, len(page_files)
    raise SystemExit(f"missing local Taginfo rows under {download_dir}; run download.sh first")


series_meta = {
    "taginfo_tag_count_all": ("uint", 64, 8, "Q", "primary", "OpenStreetMap elements using the key/value tag."),
    "taginfo_tag_count_all_fraction": ("float", 64, 8, "d", "primary", "Fraction of OpenStreetMap elements using the key/value tag."),
    "taginfo_tag_count_nodes": ("uint", 64, 8, "Q", "primary", "OpenStreetMap nodes using the key/value tag."),
    "taginfo_tag_count_nodes_fraction": ("float", 64, 8, "d", "primary", "Fraction of OpenStreetMap nodes using the key/value tag."),
    "taginfo_tag_count_ways": ("uint", 64, 8, "Q", "primary", "OpenStreetMap ways using the key/value tag."),
    "taginfo_tag_count_ways_fraction": ("float", 64, 8, "d", "primary", "Fraction of OpenStreetMap ways using the key/value tag."),
    "taginfo_tag_count_relations": ("uint", 64, 8, "Q", "primary", "OpenStreetMap relations using the key/value tag."),
    "taginfo_tag_count_relations_fraction": ("float", 64, 8, "d", "primary", "Fraction of OpenStreetMap relations using the key/value tag."),
    "taginfo_tag_projects": ("uint", 16, 2, "H", "auxiliary", "Taginfo project count for the key/value tag."),
    "taginfo_tag_in_wiki": ("uint", 8, 1, "B", "auxiliary", "Boolean OSM wiki presence, encoded as 0 or 1."),
}
values: dict[str, list[int | float]] = {series_id: [] for series_id in series_meta}
source_rows, source_pages = load_source_rows()
seen_pairs: set[tuple[str, str]] = set()
skipped = 0
duplicates = 0

for row in source_rows:
    try:
        key = str(row.get("key") or "")
        value = str(row.get("value") or "")
        pair = (key, value)
        if pair in seen_pairs:
            duplicates += 1
            continue
        count_all = int(row["count_all"])
        count_all_fraction = float(row["count_all_fraction"])
        count_nodes = int(row["count_nodes"])
        count_nodes_fraction = float(row["count_nodes_fraction"])
        count_ways = int(row["count_ways"])
        count_ways_fraction = float(row["count_ways_fraction"])
        count_relations = int(row["count_relations"])
        count_relations_fraction = float(row["count_relations_fraction"])
        projects = int(row.get("projects") or 0)
    except Exception:
        skipped += 1
        continue
    if min(count_all, count_nodes, count_ways, count_relations, projects) < 0:
        skipped += 1
        continue
    if min(count_all_fraction, count_nodes_fraction, count_ways_fraction, count_relations_fraction) < 0.0:
        skipped += 1
        continue
    if not all(
        math.isfinite(value)
        for value in (count_all_fraction, count_nodes_fraction, count_ways_fraction, count_relations_fraction)
    ):
        skipped += 1
        continue
    if projects > 0xFFFF:
        skipped += 1
        continue
    seen_pairs.add(pair)
    values["taginfo_tag_count_all"].append(count_all)
    values["taginfo_tag_count_all_fraction"].append(count_all_fraction)
    values["taginfo_tag_count_nodes"].append(count_nodes)
    values["taginfo_tag_count_nodes_fraction"].append(count_nodes_fraction)
    values["taginfo_tag_count_ways"].append(count_ways)
    values["taginfo_tag_count_ways_fraction"].append(count_ways_fraction)
    values["taginfo_tag_count_relations"].append(count_relations)
    values["taginfo_tag_count_relations_fraction"].append(count_relations_fraction)
    values["taginfo_tag_projects"].append(projects)
    values["taginfo_tag_in_wiki"].append(1 if row.get("in_wiki") else 0)

retained = len(values["taginfo_tag_count_all"])
if retained < min_retained:
    raise SystemExit(f"only {retained} retained rows < TAGINFO_TAGS_MIN_RETAINED_RECORDS={min_retained}")

lengths = {len(series_values) for series_values in values.values()}
if lengths != {retained}:
    raise SystemExit(f"series length mismatch: {sorted(lengths)}")

for series_id, series_values in values.items():
    if min(series_values) == max(series_values):
        raise SystemExit(f"constant sample after filtering: {series_id}")

for child in samples_dir.glob("*"):
    if child.is_dir():
        shutil.rmtree(child)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

rows = []
for series_id, (kind, bits, element_size, code, role, description) in series_meta.items():
    series_values = values[series_id]
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_{kind}{bits}_n{len(series_values):06d}.bin"
    with out.open("wb") as fh:
        for offset in range(0, len(series_values), 8192):
            chunk = series_values[offset : offset + 8192]
            fh.write(struct.pack("<" + code * len(chunk), *chunk))
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": role,
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": element_size,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(series_values),
            "sample_format": f"raw homogeneous {kind}{bits} array",
            "sample_geometry": "taginfo_popular_tag_column",
            "sample_rank": 1,
            "sample_shape": [len(series_values)],
            "sample_axes": ["tag"],
            "natural_record_kind": "taginfo_popular_tag_row",
            "natural_record_count": retained,
            "description": description,
            "min": min(series_values),
            "max": max(series_values),
        }
    )

primary_counts = [int(row["value_count"]) for row in rows if row["role"] == "primary"]
primary_bytes = [int(row["sample_size_bytes"]) for row in rows if row["role"] == "primary"]
primary_values = sum(primary_counts)
primary_sample_bytes = sum(primary_bytes)
median_primary_values = statistics.median(primary_counts)
if primary_values < min_primary_values:
    raise SystemExit(f"primary_values below repair target: {primary_values} < {min_primary_values}")
if primary_sample_bytes < min_primary_bytes:
    raise SystemExit(f"primary_sample_bytes below floor: {primary_sample_bytes} < {min_primary_bytes}")
if median_primary_values < min_median_values:
    raise SystemExit(f"median primary values below floor: {median_primary_values} < {min_median_values}")

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "source_pages": source_pages,
            "source_rows": len(source_rows),
            "retained_records": retained,
            "skipped_records": skipped,
            "duplicate_records": duplicates,
            "primary_values": primary_values,
            "primary_sample_bytes": primary_sample_bytes,
            "median_primary_values": median_primary_values,
            "min_retained_records": min_retained,
            "min_primary_values": min_primary_values,
            "min_primary_bytes": min_primary_bytes,
            "min_median_values": min_median_values,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"retained_records={retained} primary_values={primary_values} "
    f"primary_sample_bytes={primary_sample_bytes} median_primary_values={median_primary_values}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
