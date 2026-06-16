#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="europe_pmc_search"
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

DATASET_ID = "europe_pmc_search"
MIN_RECORDS = 10_000
MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000

SERIES = {
    "europepmc_first_publication_date": ("auxiliary", "uint", 32, "I", "Publication date as Unix epoch seconds at UTC midnight."),
    "europepmc_cited_by_count": ("primary", "uint", 32, "I", "Europe PMC citedByCount value."),
    "europepmc_author_count": ("primary", "uint", 16, "H", "Author count parsed from Europe PMC authorString."),
    "europepmc_title_length": ("primary", "uint", 16, "H", "UTF-8 code point length of the title field."),
    "europepmc_pub_type_count": ("primary", "uint", 16, "H", "Semicolon-separated publication-type count."),
    "europepmc_fulltext_id_count": ("primary", "uint", 16, "H", "Number of full-text ids attached to the record."),
    "europepmc_journal_title_length": ("primary", "uint", 16, "H", "UTF-8 code point length of the journalTitle field."),
}

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
inventory_path = download_dir / "download_inventory.json"
if not inventory_path.exists():
    raise SystemExit(f"missing download inventory: {inventory_path}; run datasets/europe_pmc_search/download.sh first")


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def bounded_u16(value: int, field: str, key: tuple[str, str]) -> int:
    if value < 0 or value > 65_535:
        raise ValueError(f"{key}: {field} outside uint16 range: {value}")
    return value


def parse_date(raw: object) -> int:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("missing date")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return calendar.timegm(datetime.strptime(text[:10], fmt).utctimetuple())
        except ValueError:
            pass
    raise ValueError(f"bad date: {text}")


def int_field(item: dict, name: str, default: int = 0) -> int:
    raw = item.get(name, default)
    if raw in (None, ""):
        return default
    return int(raw)


def author_count(item: dict) -> int:
    text = str(item.get("authorString") or "").strip()
    if not text:
        return 0
    text = text.rstrip(".")
    return sum(1 for part in text.split(",") if part.strip())


def pub_type_count(item: dict) -> int:
    text = str(item.get("pubType") or "").strip()
    if not text:
        return 0
    return sum(1 for part in text.split(";") if part.strip())


def fulltext_id_count(item: dict) -> int:
    value = item.get("fullTextIdList")
    if isinstance(value, dict):
        ids = value.get("fullTextId", [])
        if isinstance(ids, list):
            return len(ids)
        if ids:
            return 1
    if isinstance(value, list):
        return len(value)
    return 0


inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
records = inventory.get("records", [])
if not records:
    raise SystemExit("download inventory has no page records")

by_key: dict[tuple[str, str], dict] = {}
raw_records = 0
malformed = 0
for record in records:
    path = download_dir / record["local_name"]
    if not path.exists():
        raise SystemExit(f"missing downloaded page: {path}")
    obj = json.load(open(path, encoding="utf-8"))
    results = obj.get("resultList", {}).get("result", [])
    if not isinstance(results, list):
        raise SystemExit(f"bad Europe PMC result list: {path}")
    raw_records += len(results)
    for item in results:
        source = str(item.get("source", "")).strip()
        item_id = str(item.get("id", "")).strip()
        if not source or not item_id:
            malformed += 1
            continue
        by_key[(source, item_id)] = item

rows_for_values = []
for key, item in by_key.items():
    try:
        first_publication_date = parse_date(item.get("firstPublicationDate"))
        row = {
            "key": key,
            "first_publication_date": first_publication_date,
            "cited_by_count": int_field(item, "citedByCount"),
            "author_count": bounded_u16(author_count(item), "author_count", key),
            "title_length": bounded_u16(len(str(item.get("title") or "")), "title_length", key),
            "pub_type_count": bounded_u16(pub_type_count(item), "pub_type_count", key),
            "fulltext_id_count": bounded_u16(fulltext_id_count(item), "fulltext_id_count", key),
            "journal_title_length": bounded_u16(len(str(item.get("journalTitle") or "")), "journal_title_length", key),
        }
        if row["cited_by_count"] < 0:
            raise ValueError(f"{key}: negative citedByCount")
    except Exception:
        malformed += 1
        continue
    rows_for_values.append(row)

rows_for_values.sort(key=lambda item: (item["first_publication_date"], item["key"][0], item["key"][1]))
if len(rows_for_values) < MIN_RECORDS:
    raise SystemExit(f"kept Europe PMC records below repair floor: {len(rows_for_values)} < {MIN_RECORDS}")

values_by_series = {
    "europepmc_first_publication_date": [item["first_publication_date"] for item in rows_for_values],
    "europepmc_cited_by_count": [item["cited_by_count"] for item in rows_for_values],
    "europepmc_author_count": [item["author_count"] for item in rows_for_values],
    "europepmc_title_length": [item["title_length"] for item in rows_for_values],
    "europepmc_pub_type_count": [item["pub_type_count"] for item in rows_for_values],
    "europepmc_fulltext_id_count": [item["fulltext_id_count"] for item in rows_for_values],
    "europepmc_journal_title_length": [item["journal_title_length"] for item in rows_for_values],
}

for sid, values in values_by_series.items():
    role, _kind, _bits, _code, _description = SERIES[sid]
    if role == "primary" and len(set(values)) <= 1:
        raise SystemExit(f"constant primary series rejected: {sid}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
series_stats = {}
for sid, values in values_by_series.items():
    role, kind, bits, code, _description = SERIES[sid]
    out_dir = samples_dir / sid
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    index_rows.append(
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
            "sample_axes": ["publication_sorted_by_first_publication_date"],
        }
    )
    series_stats[sid] = {
        "role": role,
        "count": len(values),
        "bytes": out.stat().st_size,
        "min": min(values),
        "max": max(values),
        "distinct_prefix_200k": len(set(values[:200_000])),
    }

primary_rows = [row for row in index_rows if row["role"] == "primary"]
primary_values = sum(int(row["value_count"]) for row in primary_rows)
primary_bytes = sum(int(row["sample_size_bytes"]) for row in primary_rows)
median_values = statistics.median(int(row["value_count"]) for row in primary_rows)
if primary_values < MIN_PRIMARY_VALUES:
    raise SystemExit(f"primary values below floor: {primary_values}")
if primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {primary_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")

stats = {
    "dataset_id": DATASET_ID,
    "query": inventory.get("query"),
    "start_date": inventory.get("start_date"),
    "end_date": inventory.get("end_date"),
    "download_page_count": len(records),
    "source_bytes": inventory.get("source_bytes", 0),
    "raw_records": raw_records,
    "unique_records": len(by_key),
    "kept_records": len(rows_for_values),
    "malformed_or_skipped_records": malformed,
    "primary_values": primary_values,
    "primary_bytes": primary_bytes,
    "median_primary_values": int(median_values),
    "series": series_stats,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (filter_dir / "series_stats.tsv").open("w", encoding="utf-8") as fh:
    fh.write("series_id\trole\tcount\tbytes\tmin\tmax\tdistinct_prefix_200k\n")
    for sid in SERIES:
        entry = series_stats[sid]
        fh.write(
            f"{sid}\t{entry['role']}\t{entry['count']}\t{entry['bytes']}\t"
            f"{entry['min']}\t{entry['max']}\t{entry['distinct_prefix_200k']}\n"
        )
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={len(index_rows)} kept_records={len(rows_for_values)} "
    f"primary_values={primary_values} primary_bytes={primary_bytes} "
    f"median_values={int(median_values)} source_bytes={stats['source_bytes']}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
