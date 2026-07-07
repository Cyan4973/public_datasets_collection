#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openalex_author_topic_count_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
PAGE_DIR="$DOWNLOAD_DIR/pages"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

SHARD_VALUES="${OPENALEX_TOPIC_COUNT_SHARD_VALUES:-262144}"
MIN_FINAL_SHARD_VALUES="${OPENALEX_TOPIC_COUNT_MIN_FINAL_SHARD_VALUES:-65536}"

export REPO_ROOT DATA_DIR PAGE_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR SHARD_VALUES MIN_FINAL_SHARD_VALUES
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
page_dir = Path(os.environ["PAGE_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
shard_values = int(os.environ["SHARD_VALUES"])
min_final_shard_values = int(os.environ["MIN_FINAL_SHARD_VALUES"])

if shard_values < 1000:
    raise SystemExit(f"OPENALEX_TOPIC_COUNT_SHARD_VALUES too small: {shard_values}")
if min_final_shard_values < 1000 or min_final_shard_values > shard_values:
    raise SystemExit(f"invalid OPENALEX_TOPIC_COUNT_MIN_FINAL_SHARD_VALUES: {min_final_shard_values}")

page_re = re.compile(r"topic_count_page_(\d+)\.json$")
page_paths = sorted(
    [p for p in page_dir.glob("topic_count_page_*.json") if page_re.search(p.name)],
    key=lambda p: int(page_re.search(p.name).group(1)),
)
if not page_paths:
    raise SystemExit(f"no downloaded OpenAlex pages found under {page_dir}")

series_id = "openalex_author_topic_count_u8"
series_dir = samples_dir / series_id
if samples_dir.exists():
    shutil.rmtree(samples_dir)
series_dir.mkdir(parents=True, exist_ok=True)

index_rows: list[dict[str, object]] = []
histogram: Counter[int] = Counter()
seen_ids: set[str] = set()
rows_total = 0
rows_kept = 0
rows_skipped = 0
duplicate_ids = 0
shard_index = 0
buffer = bytearray()

def flush_shard(force: bool = False) -> None:
    global shard_index, buffer
    if not buffer:
        return
    if len(buffer) < min_final_shard_values and not force:
        return
    out = series_dir / f"part{shard_index:04d}_n{len(buffer):06d}.bin"
    out.write_bytes(buffer)
    index_rows.append(
        {
            "dataset_id": "openalex_author_topic_count_u8",
            "series_id": series_id,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(buffer),
            "value_count": len(buffer),
            "sample_geometry": "contiguous_author_topic_count_shard",
            "sample_rank": 1,
            "sample_shape": [len(buffer)],
            "shard_index": shard_index,
            "source_row_count": len(buffer),
            "natural_record_kind": "openalex_author_row",
            "natural_record_count": len(buffer),
            "natural_record_values": 1,
        }
    )
    shard_index += 1
    buffer = bytearray()

for path in page_paths:
    with path.open(encoding="utf-8") as fh:
        obj = json.load(fh)
    for item in obj["results"]:
        rows_total += 1
        entity_id = item.get("id")
        if not isinstance(entity_id, str) or not entity_id:
            rows_skipped += 1
            continue
        if entity_id in seen_ids:
            duplicate_ids += 1
            rows_skipped += 1
            continue
        seen_ids.add(entity_id)
        topics = item.get("topics") or []
        if not isinstance(topics, list):
            rows_skipped += 1
            continue
        value = min(len(topics), 255)
        buffer.append(value)
        histogram[value] += 1
        rows_kept += 1
        if len(buffer) == shard_values:
            flush_shard(force=True)

dropped_tail_values = 0
if buffer:
    if len(buffer) >= min_final_shard_values:
        flush_shard(force=True)
    else:
        dropped_tail_values = len(buffer)
        rows_kept -= dropped_tail_values
        for value in buffer:
            histogram[value] -= 1
            if histogram[value] == 0:
                del histogram[value]
        buffer = bytearray()

if not index_rows:
    raise SystemExit("no shards emitted")

index_path = index_dir / "samples.jsonl"
with index_path.open("w", encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

stats_out = {
    "dataset_id": "openalex_author_topic_count_u8",
    "downloaded_pages": len(page_paths),
    "duplicate_ids": duplicate_ids,
    "dropped_tail_values": dropped_tail_values,
    "histogram": {str(k): histogram[k] for k in sorted(histogram)},
    "rows_kept": rows_kept,
    "rows_skipped": rows_skipped,
    "rows_total": rows_total,
    "sample_count": len(index_rows),
    "shard_values": shard_values,
    "primary_values": sum(int(row["value_count"]) for row in index_rows),
    "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in index_rows),
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print(
    f"built shards={len(index_rows)} rows_kept={rows_kept} rows_skipped={rows_skipped} "
    f"primary_values={stats_out['primary_values']} primary_bytes={stats_out['primary_sample_bytes']}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
