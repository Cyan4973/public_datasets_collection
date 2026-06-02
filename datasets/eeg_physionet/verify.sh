#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="eeg_physionet"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
INDEX_PATH="$INDEX_DIR/samples.jsonl" FILTER_PATH="$FILTER_DIR/inventory.tsv" REPO_ROOT="$REPO_ROOT" DATA_DIR="$DATA_DIR" python3 - <<'PY'
import json
import os
from pathlib import Path

index_path = Path(os.environ["INDEX_PATH"])
filter_path = Path(os.environ["FILTER_PATH"])
repo_root = Path(os.environ["REPO_ROOT"])
data_dir = os.environ["DATA_DIR"]
if not index_path.exists():
    raise SystemExit(f"missing index: {index_path}")
if not filter_path.exists():
    raise SystemExit(f"missing inventory: {filter_path}")

rows = 0
series_counts = {}
for line in index_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    obj = json.loads(line)
    p = repo_root / data_dir / obj["sample_path"]
    if not p.exists():
        raise SystemExit(f"missing sample: {p}")
    size = p.stat().st_size
    if size != obj["sample_size_bytes"]:
        raise SystemExit(f"size mismatch: {p}")
    if size % obj["element_size_bytes"] != 0:
        raise SystemExit(f"alignment mismatch: {p}")
    rows += 1
    series_counts[obj["series_id"]] = series_counts.get(obj["series_id"], 0) + 1

if rows != 30:
    raise SystemExit(f"unexpected sample count: {rows}")
for series_id in ("eeg_c3", "eeg_cz", "eeg_c4"):
    if series_counts.get(series_id) != 10:
        raise SystemExit(f"unexpected per-series count for {series_id}: {series_counts.get(series_id)}")

print(f"verified_rows={rows}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
