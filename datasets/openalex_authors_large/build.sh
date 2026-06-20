#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openalex_authors_large"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

export REPO_ROOT DATA_DIR PAGE_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import shutil
import struct
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
page_dir = Path(os.environ["PAGE_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

page_re = re.compile(r"authors_page_(\d+)\.json$")
page_paths = sorted(
    [p for p in page_dir.glob("authors_page_*.json") if page_re.search(p.name)],
    key=lambda p: int(page_re.search(p.name).group(1)),
)
if not page_paths:
    raise SystemExit(f"no downloaded OpenAlex pages found under {page_dir}")

# series_id -> (numeric_kind, bit_width, struct_code)
meta = {
    "openalex_author_works_count_u32": ("uint", 32, "I"),
    "openalex_author_cited_by_count_u32": ("uint", 32, "I"),
    "openalex_author_h_index_u16": ("uint", 16, "H"),
    "openalex_author_i10_index_u32": ("uint", 32, "I"),
    "openalex_author_raw_name_count_u8": ("uint", 8, "B"),
    "openalex_author_affiliation_count_u16": ("uint", 16, "H"),
    "openalex_author_topic_count_u8": ("uint", 8, "B"),
}
vals: dict[str, list] = {sid: [] for sid in meta}
if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
for sid in vals:
    (samples_dir / sid).mkdir(parents=True, exist_ok=True)


def as_uint(value: object, key: str, max_value: int) -> int:
    count = int(value)
    if count < 0 or count > max_value:
        raise ValueError(f"{key} out of range [0, {max_value}]: {count}")
    return count


def count_array(item: dict, key: str, max_value: int) -> int:
    value = item.get(key) or []
    if not isinstance(value, list):
        raise ValueError(f"{key} is not a list")
    return min(len(value), max_value)


rows_total = 0
rows_skipped = 0
seen_ids: set[str] = set()
for path in page_paths:
    with path.open(encoding="utf-8") as fh:
        obj = json.load(fh)
    for item in obj["results"]:
        rows_total += 1
        before = len(vals["openalex_author_works_count_u32"])
        try:
            entity_id = item["id"]
            if entity_id in seen_ids:
                raise ValueError(f"duplicate OpenAlex author id {entity_id}")
            seen_ids.add(entity_id)
            stats = item.get("summary_stats") or {}
            vals["openalex_author_works_count_u32"].append(as_uint(item["works_count"], "works_count", 0xFFFFFFFF))
            vals["openalex_author_cited_by_count_u32"].append(as_uint(item["cited_by_count"], "cited_by_count", 0xFFFFFFFF))
            vals["openalex_author_h_index_u16"].append(as_uint(stats.get("h_index") or 0, "h_index", 0xFFFF))
            vals["openalex_author_i10_index_u32"].append(as_uint(stats.get("i10_index") or 0, "i10_index", 0xFFFFFFFF))
            vals["openalex_author_raw_name_count_u8"].append(count_array(item, "raw_author_names", 255))
            vals["openalex_author_affiliation_count_u16"].append(count_array(item, "affiliations", 0xFFFF))
            vals["openalex_author_topic_count_u8"].append(count_array(item, "topics", 255))
        except Exception:
            for series_values in vals.values():
                while len(series_values) > before:
                    series_values.pop()
            rows_skipped += 1

kept_rows = len(vals["openalex_author_works_count_u32"])
if len({len(series_values) for series_values in vals.values()}) != 1:
    raise SystemExit("series length mismatch after filtering")
if kept_rows == 0:
    raise SystemExit("no rows kept")

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append(
        {
            "dataset_id": "openalex_authors_large",
            "series_id": sid,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_geometry": "table_column",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "table_row_count": kept_rows,
            "table_column_count": len(meta),
            "natural_record_kind": "openalex_author_row",
            "natural_record_count": kept_rows,
            "natural_record_values": len(meta),
        }
    )

primary_bytes = sum(row["sample_size_bytes"] for row in rows)
primary_values = sum(row["value_count"] for row in rows)
stats_out = {
    "dataset_id": "openalex_authors_large",
    "downloaded_pages": len(page_paths),
    "rows_total": rows_total,
    "rows_skipped": rows_skipped,
    "rows_kept": kept_rows,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built rows_kept={kept_rows} rows_skipped={rows_skipped} primary_values={primary_values} primary_bytes={primary_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
