#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dwd_radolan_rw_precip_i16"
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

import bz2
import array
import json
import os
import shutil
import statistics
from collections import Counter
from pathlib import Path

DATASET_ID = "dwd_radolan_rw_precip_i16"
SERIES_ID = "dwd_radolan_rw_precip_words_u16"
EXPECTED_PAYLOAD = 900 * 900 * 2
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
plan = download_dir / "download_plan.tsv"
if not plan.exists():
    raise SystemExit(f"missing download plan: {plan}")

out_dir = samples_dir / SERIES_ID
if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
records = []
for line_number, line in enumerate(plan.read_text(encoding="utf-8").splitlines(), start=1):
    if not line.strip():
        continue
    name = line.split("\t", 1)[0]
    source = download_dir / name
    raw = bz2.decompress(source.read_bytes())
    header_end = raw.index(b"\x03") + 1
    payload = raw[header_end:]
    if len(payload) != EXPECTED_PAYLOAD:
        raise SystemExit(f"{name}: unexpected payload length {len(payload)}")
    words = array.array("H")
    words.frombytes(payload)
    if len(words) != 900 * 900:
        raise SystemExit(f"{name}: unexpected word count {len(words)}")
    word_min = min(words)
    word_max = max(words)
    if word_min == word_max:
        raise SystemExit(f"{name}: degenerate raster")
    out = out_dir / f"{line_number:04d}_{source.stem.removesuffix('.bin')}.bin"
    out.write_bytes(payload)
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "uint",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": len(payload),
        "value_count": len(payload) // 2,
        "sample_format": "raw homogeneous uint16 array",
        "sample_geometry": "2d_raster",
        "sample_rank": 2,
        "sample_shape": [900, 900],
        "sample_axes": ["y", "x"],
        "natural_record_kind": "dwd_radolan_rw_precipitation_composite",
        "source_file": name,
        "grid_width": 900,
        "grid_height": 900,
        "min": int(word_min),
        "max": int(word_max),
    }
    rows.append(row)
    records.append({"source_file": name, "header_bytes": header_end, "bytes": len(payload), "values": len(payload) // 2, "min": int(word_min), "max": int(word_max)})

sizes = [row["sample_size_bytes"] for row in rows]
total = sum(sizes)
if total > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary payload exceeds 1 GB cap: {total}")
if len(rows) < 24:
    raise SystemExit(f"too few RADOLAN samples: {len(rows)}")
stats = {
    "dataset_id": DATASET_ID,
    "sample_count": len(rows),
    "primary_values": sum(row["value_count"] for row in rows),
    "primary_bytes": total,
    "same_size_fraction": max(Counter(sizes).values()) / len(sizes),
    "records": records,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(f"built_samples={len(rows)} primary_bytes={total} size_range={min(sizes)}/{statistics.median(sizes)}/{max(sizes)}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
