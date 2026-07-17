#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_books_1gram_counts_2020_eng_u64"
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

MIN_OBSERVATIONS="${GOOGLE_BOOKS_NGRAM_BUILD_MIN_OBSERVATIONS:-20000000}"
MAX_PRIMARY_BYTES="${GOOGLE_BOOKS_NGRAM_MAX_PRIMARY_BYTES:-950000000}"
HARD_MAX_PRIMARY_BYTES=1000000000
if (( MAX_PRIMARY_BYTES > HARD_MAX_PRIMARY_BYTES )); then
  echo "requested max primary bytes $MAX_PRIMARY_BYTES exceeds hard cap $HARD_MAX_PRIMARY_BYTES; clamping"
  MAX_PRIMARY_BYTES="$HARD_MAX_PRIMARY_BYTES"
fi

export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_OBSERVATIONS MAX_PRIMARY_BYTES
python3 - <<'PY'
from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
from array import array
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_observations = int(os.environ["MIN_OBSERVATIONS"])
max_primary_bytes = int(os.environ["MAX_PRIMARY_BYTES"])

DATASET_ID = "google_books_1gram_counts_2020_eng_u64"
SOURCE = download_dir / "eng_1gram_20200217_00000_of_00024.gz"
SERIES = [
    ("year_u16", "uint", 16, "H", 2),
    ("match_count_u64", "uint", 64, "Q", 8),
    ("volume_count_u64", "uint", 64, "Q", 8),
]
BYTES_PER_OBSERVATION = sum(item[4] for item in SERIES)
CHUNK_OBSERVATIONS = 100000

if not SOURCE.is_file():
    raise SystemExit(f"missing source file: {SOURCE}")
max_observations_by_cap = max_primary_bytes // BYTES_PER_OBSERVATION
if max_observations_by_cap < min_observations:
    raise SystemExit(
        f"byte cap too small for min_observations={min_observations}: "
        f"max_observations_by_cap={max_observations_by_cap}"
    )

if samples_dir.exists():
    shutil.rmtree(samples_dir)
out_dir = samples_dir / "google_books_1gram_yearly_counts"
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

little = sys.byteorder == "little"
buffers = {series_id: array(typecode) for series_id, _, _, typecode, _ in SERIES}
paths = {series_id: out_dir / f"{series_id}.bin" for series_id, *_ in SERIES}
files = {series_id: paths[series_id].open("wb") for series_id, *_ in SERIES}
observations = 0
source_lines = 0
truncated_for_cap = False
min_year = 9999
max_year = 0
max_match_count = 0
max_volume_count = 0

def flush() -> None:
    for series_id, _, _, _, _ in SERIES:
        buf = buffers[series_id]
        if not buf:
            continue
        if little:
            buf.tofile(files[series_id])
        else:
            copy = array(buf.typecode, buf)
            copy.byteswap()
            copy.tofile(files[series_id])
        buffers[series_id] = array(buf.typecode)

try:
    with gzip.open(SOURCE, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            fields = line.split("\t")
            if len(fields) < 2:
                raise SystemExit(f"bad ngram row without observations near line {source_lines + 1}")
            for obs in fields[1:]:
                if observations >= max_observations_by_cap:
                    truncated_for_cap = True
                    break
                parts = obs.split(",")
                if len(parts) != 3:
                    raise SystemExit(f"bad observation near line {source_lines + 1}: {obs!r}")
                year = int(parts[0])
                match_count = int(parts[1])
                volume_count = int(parts[2])
                if not (0 <= year <= 65535):
                    raise SystemExit(f"year out of uint16 range near line {source_lines + 1}: {year}")
                if match_count < 0 or volume_count < 0:
                    raise SystemExit(f"negative count near line {source_lines + 1}: {obs!r}")
                buffers["year_u16"].append(year)
                buffers["match_count_u64"].append(match_count)
                buffers["volume_count_u64"].append(volume_count)
                min_year = min(min_year, year)
                max_year = max(max_year, year)
                max_match_count = max(max_match_count, match_count)
                max_volume_count = max(max_volume_count, volume_count)
                observations += 1
                if observations % CHUNK_OBSERVATIONS == 0:
                    flush()
            source_lines += 1
            if truncated_for_cap:
                break
    flush()
finally:
    for fh in files.values():
        fh.close()

if observations < min_observations:
    raise SystemExit(f"too few observations after build: {observations} < {min_observations}")

records: list[dict[str, object]] = []
total_bytes = 0
for series_id, numeric_kind, bit_width, _, element_size in SERIES:
    path = paths[series_id]
    size = path.stat().st_size
    expected = observations * element_size
    if size != expected:
        raise SystemExit(f"size mismatch for {series_id}: {size} != {expected}")
    total_bytes += size
    records.append({
        "dataset_id": DATASET_ID,
        "series_id": f"google_books_1gram_{series_id}",
        "family": "google_books_1gram_yearly_counts",
        "role": "primary",
        "sample_path": path.relative_to(data_root).as_posix(),
        "numeric_kind": numeric_kind,
        "bit_width": bit_width,
        "endianness": "little",
        "element_size_bytes": element_size,
        "sample_size_bytes": size,
        "value_count": observations,
        "sample_geometry": "observation_field",
        "sample_rank": 1,
        "sample_shape": [observations],
        "sample_axes": ["ngram_year_observation"],
        "source_path": SOURCE.as_posix(),
        "natural_record_kind": "google_books_1gram_yearly_observation",
    })

if total_bytes > max_primary_bytes:
    raise SystemExit(f"primary output exceeds cap: {total_bytes} > {max_primary_bytes}")

stats = {
    "dataset_id": DATASET_ID,
    "source_file": SOURCE.name,
    "source_bytes": SOURCE.stat().st_size,
    "source_lines_processed": source_lines,
    "observations": observations,
    "truncated_for_cap": truncated_for_cap,
    "samples": len(records),
    "primary_values": sum(record["value_count"] for record in records),
    "primary_sample_bytes": total_bytes,
    "min_year": min_year,
    "max_year": max_year,
    "max_match_count": max_match_count,
    "max_volume_count": max_volume_count,
    "max_primary_bytes": max_primary_bytes,
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as out:
    for record in records:
        out.write(json.dumps(record, sort_keys=True) + "\n")

print(
    f"built samples={len(records)} observations={observations} "
    f"values={stats['primary_values']} bytes={total_bytes} "
    f"truncated_for_cap={truncated_for_cap}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
