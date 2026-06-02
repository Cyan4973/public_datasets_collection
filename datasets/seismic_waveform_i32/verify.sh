#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="seismic_waveform_i32"
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
import json
import os
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])

expected = {
    "anchorage_cola": 24000,
    "chile_hrv": 12000,
    "haiti_hrv": 12000,
    "kumamoto_majo": 12000,
    "mexico_anmo": 12000,
    "nepal_tuc": 12000,
    "nz_snzo": 12000,
    "okhotsk_cola": 12000,
    "quiet_anmo": 24000,
    "sumatra_cola": 12000,
    "tohoku_anmo": 12000,
    "turkey_kev": 12000,
}

for stem in expected:
    source = download_dir / f"{stem}.ascii"
    if not source.is_file():
        raise SystemExit(f"missing raw file: {source}")

stats_path = filter_dir / "ingest_stats.json"
index_path = index_dir / "samples.jsonl"
if not stats_path.is_file():
    raise SystemExit(f"missing stats file: {stats_path}")
if not index_path.is_file():
    raise SystemExit(f"missing sample index: {index_path}")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
if stats["total_files"] != len(expected):
    raise SystemExit(f"unexpected total_files: {stats['total_files']}")

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != len(expected):
    raise SystemExit(f"unexpected index row count: {len(rows)}")

seen = set()
for row in rows:
    sample_path = data_root / row["sample_path"]
    stem = sample_path.stem
    seen.add(stem)
    expected_values = expected.get(stem)
    if expected_values is None:
        raise SystemExit(f"unexpected sample stem: {stem}")
    if row["dataset_id"] != "seismic_waveform_i32" or row["series_id"] != "seismic_waveform_i32":
        raise SystemExit(f"unexpected row ids: {row}")
    if row["numeric_kind"] != "int" or row["bit_width"] != 32 or row["endianness"] != "little":
        raise SystemExit(f"unexpected row metadata: {row}")
    if row["value_count"] != expected_values:
        raise SystemExit(f"unexpected value_count for {stem}: {row['value_count']}")
    if row["sample_size_bytes"] != expected_values * 4:
        raise SystemExit(f"unexpected sample_size_bytes for {stem}: {row['sample_size_bytes']}")
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    if sample_path.stat().st_size != expected_values * 4:
        raise SystemExit(f"bad sample byte size for {sample_path}: {sample_path.stat().st_size}")

if seen != set(expected):
    raise SystemExit("sample set mismatch")

print(f"verified_samples={len(rows)}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
