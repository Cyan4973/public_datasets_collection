#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="taginfo_keys_all"
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
export TAGINFO_MIN_RETAINED_RECORDS="${TAGINFO_MIN_RETAINED_RECORDS:-2000}"
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import statistics
import struct
from pathlib import Path

DATASET_ID = "taginfo_keys_all"
repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_retained = int(os.environ["TAGINFO_MIN_RETAINED_RECORDS"])


def load_source_rows() -> tuple[list[dict], int]:
    page_dir = download_dir / "pages"
    page_files = sorted(page_dir.glob("page_*.json"))
    if page_files:
        source_rows: list[dict] = []
        for page_file in page_files:
            obj = json.loads(page_file.read_text(encoding="utf-8"))
            data = obj.get("data")
            if not isinstance(data, list):
                raise SystemExit(f"{page_file}: missing data list")
            source_rows.extend(data)
        return source_rows, len(page_files)

    legacy = download_dir / "taginfo_keys_all.json"
    if legacy.is_file():
        obj = json.loads(legacy.read_text(encoding="utf-8"))
        data = obj.get("data")
        if isinstance(data, list):
            return data, 1
    raise SystemExit(f"missing local Taginfo data under {download_dir}; run download.sh first")


def as_uint(row: dict, key: str, max_value: int) -> int:
    value = int(row[key])
    if value < 0 or value > max_value:
        raise ValueError(f"{key} out of range [0, {max_value}]: {value}")
    return value


source_rows, source_pages = load_source_rows()
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

series_meta = {
    "taginfo_count_all": ("uint", 64, 8, "Q", "OpenStreetMap elements using the key."),
    "taginfo_count_nodes": ("uint", 64, 8, "Q", "OpenStreetMap nodes using the key."),
    "taginfo_count_ways": ("uint", 64, 8, "Q", "OpenStreetMap ways using the key."),
    "taginfo_count_relations": ("uint", 64, 8, "Q", "OpenStreetMap relations using the key."),
    "taginfo_values_all": ("uint", 64, 8, "Q", "Distinct values observed for the key."),
    "taginfo_users_all": ("uint", 64, 8, "Q", "Distinct mappers observed for the key."),
    "taginfo_in_wiki": ("uint", 8, 1, "B", "Boolean presence in the OSM wiki, encoded as 0 or 1."),
    "taginfo_projects": ("uint", 16, 2, "H", "Project count reported by Taginfo for the key."),
}
values: dict[str, list[int]] = {series_id: [] for series_id in series_meta}
seen_keys: set[str] = set()
skipped = 0
duplicates = 0

for row in source_rows:
    before = len(values["taginfo_count_all"])
    try:
        key = str(row.get("key") or "")
        if key and key in seen_keys:
            duplicates += 1
            continue
        count_all = as_uint(row, "count_all", 0xFFFFFFFFFFFFFFFF)
        count_nodes = as_uint(row, "count_nodes", 0xFFFFFFFFFFFFFFFF)
        count_ways = as_uint(row, "count_ways", 0xFFFFFFFFFFFFFFFF)
        count_relations = as_uint(row, "count_relations", 0xFFFFFFFFFFFFFFFF)
        values_all = as_uint(row, "values_all", 0xFFFFFFFFFFFFFFFF)
        users_all = as_uint(row, "users_all", 0xFFFFFFFFFFFFFFFF)
        projects = int(row.get("projects") or 0)
        if projects < 0 or projects > 0xFFFF:
            raise ValueError(f"projects out of uint16 range: {projects}")
    except Exception:
        for series_values in values.values():
            while len(series_values) > before:
                series_values.pop()
        skipped += 1
        continue

    if key:
        seen_keys.add(key)
    values["taginfo_count_all"].append(count_all)
    values["taginfo_count_nodes"].append(count_nodes)
    values["taginfo_count_ways"].append(count_ways)
    values["taginfo_count_relations"].append(count_relations)
    values["taginfo_values_all"].append(values_all)
    values["taginfo_users_all"].append(users_all)
    values["taginfo_in_wiki"].append(1 if row.get("in_wiki") else 0)
    values["taginfo_projects"].append(projects)

retained = len(values["taginfo_count_all"])
if retained < min_retained:
    raise SystemExit(f"only {retained} retained rows < TAGINFO_MIN_RETAINED_RECORDS={min_retained}; rerun download.sh")

lengths = {len(series_values) for series_values in values.values()}
if lengths != {retained}:
    raise SystemExit(f"series length mismatch: {sorted(lengths)}")

for series_id, (kind, bits, element_size, code, description) in series_meta.items():
    series_values = values[series_id]
    if min(series_values) == max(series_values):
        raise SystemExit(f"constant sample after filtering: {series_id}")

counts = [len(series_values) for series_values in values.values()]
byte_counts = [
    len(values[series_id]) * element_size
    for series_id, (_kind, _bits, element_size, _code, _description) in series_meta.items()
]
if sum(counts) < 10_000 and sum(byte_counts) < 102_400:
    raise SystemExit(f"below aggregate floor: values={sum(counts)} bytes={sum(byte_counts)}")
if statistics.median(counts) < 1_000:
    raise SystemExit(f"median sample values below floor: {statistics.median(counts)}")

for child in samples_dir.glob("*"):
    if child.is_dir():
        shutil.rmtree(child)

rows = []
for series_id, (kind, bits, element_size, code, description) in series_meta.items():
    series_values = values[series_id]
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{series_id}_n{len(series_values):06d}.bin"
    with out.open("wb") as fh:
        for offset in range(0, len(series_values), 8192):
            chunk = series_values[offset : offset + 8192]
            fh.write(struct.pack("<" + code * len(chunk), *chunk))
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": element_size,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(series_values),
            "sample_format": f"raw homogeneous {kind}{bits} array",
            "sample_geometry": "taginfo_key_table_column",
            "sample_rank": 1,
            "sample_shape": [len(series_values)],
            "sample_axes": ["taginfo_key"],
            "natural_record_kind": "taginfo_key_row",
            "natural_record_count": retained,
            "natural_record_values": 1,
            "field_description": description,
            "min": min(series_values),
            "max": max(series_values),
        }
    )

(filter_dir / "ingest_stats.json").write_text(
    json.dumps(
        {
            "dataset_id": DATASET_ID,
            "source_pages": source_pages,
            "source_records": len(source_rows),
            "retained_records": retained,
            "skipped_records": skipped,
            "duplicate_records": duplicates,
            "primary_values": sum(counts),
            "primary_sample_bytes": sum(byte_counts),
            "median_primary_values": statistics.median(counts),
            "series": {
                row["series_id"]: {
                    "sample_count": 1,
                    "total_values": int(row["value_count"]),
                    "total_size_bytes": int(row["sample_size_bytes"]),
                    "min": int(row["min"]),
                    "max": int(row["max"]),
                }
                for row in rows
            },
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
    f"built samples={len(rows)} retained_records={retained} "
    f"values={sum(counts)} bytes={sum(byte_counts)} skipped={skipped} duplicates={duplicates}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
