#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="citibike_2024_01_station_ids_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])

archive = download_dir / "202401-citibike-tripdata.zip"
expected_bytes = 369035302
expected_sha256 = "0a2e81eacd7bf3890712de8f2a1b56bda985c17d9e61b08acf5e7c7ec9f20eb0"
expected_shards = [104742, 149385, 211815, 23608, 454662, 88962, 337379, 517532]
expected_series = {"citibike_start_station_id", "citibike_end_station_id"}

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

if not archive.is_file():
    raise SystemExit(f"missing archive: {archive}")
if archive.stat().st_size != expected_bytes:
    raise SystemExit(f"archive size mismatch: {archive.stat().st_size} != {expected_bytes}")
if sha256_file(archive) != expected_sha256:
    raise SystemExit("archive sha256 mismatch")

stats_path = filter_dir / "ingest_stats.json"
index_path = index_dir / "samples.jsonl"
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != 16:
    raise SystemExit(f"unexpected index row count: {len(rows)}")

by_series = {}
for row in rows:
    by_series.setdefault(row["series_id"], []).append(row)
    if row["dataset_id"] != "citibike_2024_01_station_ids_u16":
      raise SystemExit(f"unexpected dataset_id: {row}")
    if row["numeric_kind"] != "uint" or row["bit_width"] != 16 or row["endianness"] != "little":
      raise SystemExit(f"unexpected numeric metadata: {row}")

if set(by_series) != expected_series:
    raise SystemExit(f"unexpected series set: {set(by_series)}")

for series_id, series_rows in by_series.items():
    series_rows.sort(key=lambda row: row["sample_path"])
    if len(series_rows) != 8:
        raise SystemExit(f"unexpected shard count for {series_id}: {len(series_rows)}")
    for idx, (row, expected_values) in enumerate(zip(series_rows, expected_shards)):
        if row["value_count"] != expected_values:
            raise SystemExit(f"unexpected value_count for {series_id} part{idx:03d}: {row['value_count']}")
        if row["sample_size_bytes"] != expected_values * 2:
            raise SystemExit(f"unexpected sample_size_bytes for {series_id} part{idx:03d}: {row['sample_size_bytes']}")
        sample_path = data_root / row["sample_path"]
        if not sample_path.is_file():
            raise SystemExit(f"missing sample file: {sample_path}")
        if sample_path.stat().st_size != expected_values * 2:
            raise SystemExit(f"bad sample byte size for {sample_path}: {sample_path.stat().st_size}")

print(f"verified_samples={len(rows)}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
