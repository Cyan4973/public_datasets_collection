#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="librispeech_dev_clean_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR INDEX_DIR FILTER_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
import statistics
from collections import Counter
from pathlib import Path

DATASET_ID = "librispeech_dev_clean_i16"
SERIES_ID = "librispeech_dev_clean_pcm16"
MAX_PRIMARY_BYTES = 1_000_000_000

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
index_path = Path(os.environ["INDEX_DIR"]) / "samples.jsonl"
stats_path = Path(os.environ["FILTER_DIR"]) / "ingest_stats.json"
if not index_path.exists():
    raise SystemExit(f"missing sample index: {index_path}")
if not stats_path.exists():
    raise SystemExit(f"missing ingest stats: {stats_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) < 2500:
    raise SystemExit(f"too few samples: {len(rows)}")

sizes = []
values = []
speakers = set()
for row in rows:
    if row["dataset_id"] != DATASET_ID or row["series_id"] != SERIES_ID:
        raise SystemExit(f"unexpected row identity: {row}")
    if row["numeric_kind"] != "int" or int(row["bit_width"]) != 16 or row["endianness"] != "little":
        raise SystemExit(f"unexpected numeric representation: {row}")
    sample_path = data_root / row["sample_path"]
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    actual = sample_path.stat().st_size
    declared = int(row["sample_size_bytes"])
    count = int(row["value_count"])
    if actual != declared or declared != count * 2 or declared % 2:
        raise SystemExit(f"size mismatch: {sample_path}")
    sizes.append(declared)
    values.append(count)
    speakers.add(str(row.get("speaker_id", "")))

total_bytes = sum(sizes)
if total_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary payload exceeds 1 GB cap: {total_bytes}")
if statistics.median(values) < 1000:
    raise SystemExit(f"median sample below floor: {statistics.median(values)}")
same_size_fraction = max(Counter(sizes).values()) / len(sizes)
if same_size_fraction > 0.25:
    raise SystemExit(f"unexpected same-size concentration: {same_size_fraction:.6f}")
print(
    "verified_rows="
    f"{len(rows)} primary_samples={len(rows)} primary_values={sum(values)} primary_bytes={total_bytes} "
    f"speakers={len(speakers)} size_range={min(sizes)}/{statistics.median(sizes)}/{max(sizes)} "
    f"same_size_fraction={same_size_fraction:.6f}"
)
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
