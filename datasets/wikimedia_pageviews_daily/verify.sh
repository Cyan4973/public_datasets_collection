#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="wikimedia_pageviews_daily"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
import json
import os
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])

payloads = sorted(download_dir.glob("*.json"))
if len(payloads) != 7:
    raise SystemExit(f"expected 7 raw JSON payloads, found {len(payloads)}")

stats_path = filter_dir / "ingest_stats.json"
index_path = index_dir / "samples.jsonl"
if not stats_path.is_file() or not index_path.is_file():
    raise SystemExit("missing build outputs")

stats = json.loads(stats_path.read_text(encoding="utf-8"))
rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != 7:
    raise SystemExit(f"unexpected index row count: {len(rows)}")

for row in rows:
    if row["dataset_id"] != "wikimedia_pageviews_daily" or row["series_id"] != "wikimedia_daily_pageviews":
        raise SystemExit(f"bad row metadata: {row}")
    if row["numeric_kind"] != "uint" or row["bit_width"] != 32 or row["element_size_bytes"] != 4 or row["endianness"] != "little":
        raise SystemExit(f"bad row typing: {row}")
    if row["value_count"] != 366:
        raise SystemExit(f"unexpected daily count: {row}")
    sample_path = data_root / row["sample_path"]
    if not sample_path.is_file():
        raise SystemExit(f"missing sample file: {sample_path}")
    if sample_path.stat().st_size != row["sample_size_bytes"]:
        raise SystemExit(f"sample size mismatch: {sample_path}")
    if row["sample_size_bytes"] != row["value_count"] * 4:
        raise SystemExit(f"bad accounting: {row}")

if stats["series"]["wikimedia_daily_pageviews"]["files"] != 7:
    raise SystemExit("stats file count mismatch")

print(f"verified_samples={len(rows)}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
