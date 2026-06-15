#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID='internetarchive_advancedsearch'
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$INDEX_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
import json, os
from pathlib import Path
root=Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
download_dir=Path(os.environ["DOWNLOAD_DIR"])
filter_dir=Path(os.environ["FILTER_DIR"])
rows=[json.loads(line) for line in (Path(os.environ["INDEX_DIR"])/"samples.jsonl").read_text().splitlines() if line.strip()]
if len(rows) != 2: raise SystemExit(f"unexpected row count {len(rows)}")
if len({row["value_count"] for row in rows}) != 1: raise SystemExit("series length mismatch")
raw=json.load(open(download_dir/"internetarchive_advancedsearch.json",encoding="utf-8"))["response"]["docs"]
kept=0
for doc in raw:
    try:
        if not doc.get("identifier"):
            raise ValueError("missing identifier")
        int(doc["downloads"])
        int(doc["item_size"])
    except Exception:
        continue
    kept += 1
stats=json.loads((filter_dir/"ingest_stats.json").read_text(encoding="utf-8"))
if stats.get("rows_total") != len(raw):
    raise SystemExit(f"rows_total mismatch: stats={stats.get('rows_total')} raw={len(raw)}")
if stats.get("rows_kept") != kept:
    raise SystemExit(f"rows_kept mismatch: stats={stats.get('rows_kept')} raw={kept}")
if kept < 10000:
    raise SystemExit(f"kept too few rows: {kept}")
for row in rows:
    path=root/row["sample_path"]
    if not path.is_file(): raise SystemExit(f"missing sample {row['sample_path']}")
    if row["value_count"] != kept:
        raise SystemExit(f"value_count mismatch for {row['series_id']}: {row['value_count']} != {kept}")
    if row["sample_size_bytes"] != path.stat().st_size:
        raise SystemExit(f"sample_size mismatch for {row['series_id']}")
    if row["value_count"] * row["element_size_bytes"] != row["sample_size_bytes"]:
        raise SystemExit(f"bad sizing for {row['series_id']}")
print(f"verified_samples={len(rows)} rows_kept={kept}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
