#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openalex_works_2024_sample"
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
import calendar
from datetime import datetime
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
page_dir = Path(os.environ["PAGE_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])

page_re = re.compile(r"works_2024_page_(\d+)\.json$")
page_paths = sorted(
    [p for p in page_dir.glob("works_2024_page_*.json") if page_re.search(p.name)],
    key=lambda p: int(page_re.search(p.name).group(1)),
)
if not page_paths:
    raise SystemExit(f"no downloaded OpenAlex pages found under {page_dir}")

meta = {
    "openalex_publication_date": ("uint", 32, "I"),
    "openalex_cited_by_count": ("uint", 32, "I"),
    "openalex_referenced_works_count": ("uint", 32, "I"),
    "openalex_authorship_count": ("uint", 16, "H"),
    "openalex_location_count": ("uint", 16, "H"),
    "openalex_created_at": ("uint", 32, "I"),
    "openalex_updated_at": ("uint", 32, "I"),
    "openalex_countries_distinct_count": ("uint", 16, "H"),
    "openalex_institutions_distinct_count": ("uint", 16, "H"),
    "openalex_locations_count": ("uint", 16, "H"),
    "openalex_fwci": ("float", 32, "f"),
    "openalex_citation_normalized_percentile": ("float", 32, "f"),
    "openalex_primary_topic_score": ("float", 32, "f"),
    "openalex_has_fulltext": ("uint", 8, "B"),
    "openalex_is_retracted": ("uint", 8, "B"),
    "openalex_citation_top_1_percent": ("uint", 8, "B"),
    "openalex_citation_top_10_percent": ("uint", 8, "B"),
    "openalex_cited_by_percentile_year_min": ("uint", 16, "H"),
    "openalex_indexed_in_count": ("uint", 16, "H"),
    "openalex_awards_count": ("uint", 16, "H"),
    "openalex_funders_count": ("uint", 16, "H"),
    "openalex_counts_by_year_count": ("uint", 16, "H"),
    "openalex_related_works_count": ("uint", 16, "H"),
}
vals = {sid: [] for sid in meta}
if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
for sid in vals:
    (samples_dir / sid).mkdir(parents=True, exist_ok=True)

def date_to_int(value: str) -> int:
    parts = value.split("-")
    if len(parts) != 3:
        raise ValueError(f"bad publication_date {value!r}")
    year, month, day = (int(part) for part in parts)
    if year < 2024 or year > 2024 or not (1 <= month <= 12) or not (1 <= day <= 31):
        raise ValueError(f"publication_date out of scope {value!r}")
    return year * 10000 + month * 100 + day

def datetime_to_epoch(value: str) -> int:
    head = value.split(".", 1)[0]
    dt = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S")
    return calendar.timegm(dt.utctimetuple())

def as_uint16(value: object, key: str) -> int:
    count = int(value)
    if count < 0 or count > 65535:
        raise ValueError(f"{key} out of uint16 range: {count}")
    return count

def as_bool(value: object, key: str) -> int:
    if not isinstance(value, bool):
        raise ValueError(f"{key} is not a boolean")
    return 1 if value else 0

def count_array(item: dict, key: str) -> int:
    value = item.get(key) or []
    if not isinstance(value, list):
        raise ValueError(f"{key} is not a list")
    count = len(value)
    if count > 65535:
        raise ValueError(f"{key} too large for uint16: {count}")
    return count

rows_total = 0
rows_skipped = 0
seen_ids: set[str] = set()
for path in page_paths:
    with path.open(encoding="utf-8") as fh:
        obj = json.load(fh)
    for item in obj["results"]:
        rows_total += 1
        before = len(vals["openalex_publication_date"])
        try:
            work_id = item["id"]
            if work_id in seen_ids:
                raise ValueError(f"duplicate OpenAlex work id {work_id}")
            seen_ids.add(work_id)
            vals["openalex_publication_date"].append(date_to_int(item["publication_date"]))
            vals["openalex_cited_by_count"].append(int(item["cited_by_count"]))
            vals["openalex_referenced_works_count"].append(int(item["referenced_works_count"]))
            vals["openalex_authorship_count"].append(count_array(item, "authorships"))
            vals["openalex_location_count"].append(count_array(item, "locations"))
            vals["openalex_created_at"].append(datetime_to_epoch(item["created_date"]))
            vals["openalex_updated_at"].append(datetime_to_epoch(item["updated_date"]))
            vals["openalex_countries_distinct_count"].append(as_uint16(item["countries_distinct_count"], "countries_distinct_count"))
            vals["openalex_institutions_distinct_count"].append(as_uint16(item["institutions_distinct_count"], "institutions_distinct_count"))
            vals["openalex_locations_count"].append(as_uint16(item["locations_count"], "locations_count"))
            vals["openalex_fwci"].append(float(item["fwci"]))
            citation = item["citation_normalized_percentile"]
            vals["openalex_citation_normalized_percentile"].append(float(citation["value"]))
            vals["openalex_citation_top_1_percent"].append(as_bool(citation["is_in_top_1_percent"], "citation_top_1_percent"))
            vals["openalex_citation_top_10_percent"].append(as_bool(citation["is_in_top_10_percent"], "citation_top_10_percent"))
            vals["openalex_primary_topic_score"].append(float(item["primary_topic"]["score"]))
            vals["openalex_has_fulltext"].append(as_bool(item["has_fulltext"], "has_fulltext"))
            vals["openalex_is_retracted"].append(as_bool(item["is_retracted"], "is_retracted"))
            vals["openalex_cited_by_percentile_year_min"].append(as_uint16(item["cited_by_percentile_year"]["min"], "cited_by_percentile_year_min"))
            vals["openalex_indexed_in_count"].append(count_array(item, "indexed_in"))
            vals["openalex_awards_count"].append(count_array(item, "awards"))
            vals["openalex_funders_count"].append(count_array(item, "funders"))
            vals["openalex_counts_by_year_count"].append(count_array(item, "counts_by_year"))
            vals["openalex_related_works_count"].append(count_array(item, "related_works"))
        except Exception:
            for series_values in vals.values():
                while len(series_values) > before:
                    series_values.pop()
            rows_skipped += 1

kept_rows = len(vals["openalex_publication_date"])
if len({len(series_values) for series_values in vals.values()}) != 1:
    raise SystemExit("series length mismatch after filtering")

rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append(
        {
            "dataset_id": "openalex_works_2024_sample",
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
                "natural_record_kind": "openalex_work_row",
                "natural_record_count": kept_rows,
                "natural_record_values": len(meta),
            }
        )

primary_bytes = sum(row["sample_size_bytes"] for row in rows)
primary_values = sum(row["value_count"] for row in rows)
stats = {
    "dataset_id": "openalex_works_2024_sample",
    "downloaded_pages": len(page_paths),
    "rows_total": rows_total,
    "rows_skipped": rows_skipped,
    "rows_kept": kept_rows,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built rows_kept={kept_rows} rows_skipped={rows_skipped} primary_values={primary_values} primary_bytes={primary_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
