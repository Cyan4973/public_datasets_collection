#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gutendex_catalog_books"
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

pages = sorted(download_dir.glob("gutendex_catalog_books_page_*.json"))
if not pages:
    raise SystemExit(f"missing Gutendex JSON pages under {download_dir}")

for path in (filter_dir, index_dir, samples_dir):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

books_by_id: dict[int, dict] = {}
raw_rows = 0
for page in pages:
    obj = json.loads(page.read_text(encoding="utf-8"))
    results = obj.get("results")
    if not isinstance(results, list):
        raise SystemExit(f"{page.name}: missing results")
    raw_rows += len(results)
    for row in results:
        try:
            book_id = int(row["id"])
        except Exception:
            continue
        books_by_id.setdefault(book_id, row)

book_ids: list[int] = []
download_counts: list[int] = []
author_birth_years: list[int] = []
author_death_years: list[int] = []
skipped_books = 0
skipped_authors = 0
for book_id in sorted(books_by_id):
    row = books_by_id[book_id]
    try:
        download_count = int(row["download_count"])
        if book_id < 0 or download_count < 0 or book_id > 0xFFFFFFFF or download_count > 0xFFFFFFFF:
            raise ValueError("book id or download count out of uint32 range")
    except Exception:
        skipped_books += 1
        continue
    book_ids.append(book_id)
    download_counts.append(download_count)

    authors = row.get("authors") or []
    if not isinstance(authors, list):
        continue
    for author in authors:
        try:
            birth = int(author["birth_year"])
            death = int(author["death_year"])
            if not (-32768 <= birth <= 32767 and -32768 <= death <= 32767):
                raise ValueError("author year outside int16 range")
        except Exception:
            skipped_authors += 1
            continue
        author_birth_years.append(birth)
        author_death_years.append(death)

series = {
    "gutendex_download_count_u32": ("primary", "uint", 32, "I", download_counts, "gutendex_book_table_column", ["book"]),
    "gutendex_author_birth_year_i16": ("primary", "int", 16, "h", author_birth_years, "gutendex_author_record_column", ["book_author_record"]),
    "gutendex_author_death_year_i16": ("primary", "int", 16, "h", author_death_years, "gutendex_author_record_column", ["book_author_record"]),
    "gutendex_book_id_u32": ("auxiliary", "uint", 32, "I", book_ids, "gutendex_book_table_column", ["book"]),
}

rows = []
for series_id, (role, kind, bits, code, values, geometry, axes) in series.items():
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
            "role": role,
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_geometry": geometry,
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": axes,
            "source_name": "gutendex_catalog_sort_ascending",
        }
    )

primary_counts = [int(row["value_count"]) for row in rows if row["role"] == "primary"]
primary_sizes = [int(row["sample_size_bytes"]) for row in rows if row["role"] == "primary"]
stats = {
    "dataset_id": dataset_id,
    "downloaded_pages": len(pages),
    "raw_rows": raw_rows,
    "unique_books": len(books_by_id),
    "retained_books": len(book_ids),
    "skipped_books": skipped_books,
    "retained_author_records": len(author_birth_years),
    "skipped_author_records": skipped_authors,
    "primary_samples": len(primary_counts),
    "primary_values": sum(primary_counts),
    "primary_bytes": sum(primary_sizes),
    "median_primary_values": statistics.median(primary_counts) if primary_counts else 0,
    "source_bytes": sum(path.stat().st_size for path in pages),
}
if stats["primary_values"] < 10_000:
    raise SystemExit(f"primary values below floor: {stats['primary_values']}")
if stats["primary_bytes"] < 100 * 1024:
    raise SystemExit(f"primary bytes below floor: {stats['primary_bytes']}")
if stats["median_primary_values"] < 1_000:
    raise SystemExit(f"median primary sample values below floor: {stats['median_primary_values']}")

(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={len(rows)} primary_values={stats['primary_values']} "
    f"primary_bytes={stats['primary_bytes']} median_values={stats['median_primary_values']} "
    f"retained_books={stats['retained_books']} retained_author_records={stats['retained_author_records']}"
)
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
