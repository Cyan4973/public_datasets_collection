#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="medrxiv_details"
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

DATASET_ID = "medrxiv_details"
MIN_RECORDS = 10_000
MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000

PRIMARY_SERIES = {
    "medrxiv_details_version": ("uint", 16, "H", "Preprint version number."),
    "medrxiv_details_author_count": ("uint", 16, "H", "Author count parsed from the semicolon-delimited author field."),
    "medrxiv_details_abstract_length": ("uint", 32, "I", "Abstract length in source characters."),
    "medrxiv_details_title_length": ("uint", 16, "H", "Title length in source characters."),
    "medrxiv_details_corresponding_institution_length": ("uint", 16, "H", "Corresponding-author institution field length in source characters."),
}
AUX_SERIES = {
    "medrxiv_details_date": ("uint", 32, "I", "Preprint version date as Unix epoch seconds."),
}

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
inventory_path = download_dir / "download_inventory.json"
if not inventory_path.exists():
    raise SystemExit(f"missing download inventory: {inventory_path}")


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def day_ts(text: str) -> int:
    return calendar.timegm(datetime.strptime(text, "%Y-%m-%d").utctimetuple())


def bounded_u16(value: int, field: str, key: str) -> int:
    if value < 0 or value > 65535:
        raise ValueError(f"{key}: {field} outside uint16 range: {value}")
    return value


def bounded_u32(value: int, field: str, key: str) -> int:
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError(f"{key}: {field} outside uint32 range: {value}")
    return value


inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
all_items: dict[tuple[str, int], dict] = {}
raw_records = 0
for record in inventory.get("records", []):
    path = download_dir / record["local_name"]
    obj = json.load(open(path, encoding="utf-8"))
    for row in obj.get("collection", []):
        raw_records += 1
        doi = str(row.get("doi", "")).strip()
        try:
            version = int(row.get("version", ""))
        except Exception:
            continue
        if not doi:
            continue
        all_items[(doi, version)] = row

items = []
skipped = 0
for key, row in all_items.items():
    try:
        doi, version = key
        authors = [author for author in str(row.get("authors", "")).split(";") if author.strip()]
        record = {
            "doi": doi,
            "version": bounded_u16(version, "version", doi),
            "date": day_ts(str(row["date"])),
            "author_count": bounded_u16(len(authors), "author_count", doi),
            "abstract_length": bounded_u32(len(str(row.get("abstract", ""))), "abstract_length", doi),
            "title_length": bounded_u16(len(str(row.get("title", ""))), "title_length", doi),
            "corresponding_institution_length": bounded_u16(
                len(str(row.get("author_corresponding_institution", ""))),
                "corresponding_institution_length",
                doi,
            ),
        }
    except Exception:
        skipped += 1
        continue
    items.append(record)

items.sort(key=lambda item: (item["date"], item["doi"], item["version"]))
if len(items) < MIN_RECORDS:
    raise SystemExit(f"kept medRxiv records below repair floor: {len(items)} < {MIN_RECORDS}")

values_by_series = {
    "medrxiv_details_version": [item["version"] for item in items],
    "medrxiv_details_author_count": [item["author_count"] for item in items],
    "medrxiv_details_abstract_length": [item["abstract_length"] for item in items],
    "medrxiv_details_title_length": [item["title_length"] for item in items],
    "medrxiv_details_corresponding_institution_length": [item["corresponding_institution_length"] for item in items],
    "medrxiv_details_date": [item["date"] for item in items],
}

for sid in PRIMARY_SERIES:
    if len(set(values_by_series[sid])) <= 1:
        raise SystemExit(f"constant primary series rejected: {sid}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
for sid, values in values_by_series.items():
    kind, bits, code, _description = (PRIMARY_SERIES | AUX_SERIES)[sid]
    role = "primary" if sid in PRIMARY_SERIES else "auxiliary"
    out_dir = samples_dir / sid
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": sid,
            "role": role,
            "sample_path": rel(out),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["preprint_version_sorted_by_date"],
        }
    )

primary_rows = [row for row in rows if row["role"] == "primary"]
primary_counts = [row["value_count"] for row in primary_rows]
primary_sizes = [row["sample_size_bytes"] for row in primary_rows]
primary_values = sum(primary_counts)
primary_bytes = sum(primary_sizes)
median_values = statistics.median(primary_counts)
if primary_values < MIN_PRIMARY_VALUES:
    raise SystemExit(f"primary values below floor: {primary_values}")
if primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {primary_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median primary sample values below floor: {median_values}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")

stats = {
    "dataset_id": DATASET_ID,
    "download_page_count": len(inventory.get("records", [])),
    "raw_records": raw_records,
    "unique_records": len(all_items),
    "kept_records": len(items),
    "malformed_or_skipped_records": skipped,
    "source_bytes": inventory.get("source_bytes", 0),
    "primary_values": primary_values,
    "primary_bytes": primary_bytes,
    "series": {
        sid: {
            "role": "primary" if sid in PRIMARY_SERIES else "auxiliary",
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "distinct_prefix_200k": len(set(values[:200_000])),
        }
        for sid, values in values_by_series.items()
    },
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={len(rows)} primary_samples={len(primary_rows)} kept_records={len(items)} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} median_values={int(median_values)}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
