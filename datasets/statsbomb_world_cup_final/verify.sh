#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="statsbomb_world_cup_final"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
python3 - <<'PY' "$REPO_ROOT" "$DATA_DIR" "$FILTER_DIR" "$INDEX_DIR"
import json, sys
from pathlib import Path
repo_root=Path(sys.argv[1]); data_dir=sys.argv[2]; filter_dir=Path(sys.argv[3]); index_dir=Path(sys.argv[4])
stats=json.load((filter_dir/"ingest_stats.json").open())
rows=[json.loads(line) for line in (index_dir/"samples.jsonl").open()]
assert len(rows) == 9
assert stats["rows_total"]["events"] > 0 and stats["rows_total"]["matches"] > 0
for row in rows:
    sample=repo_root/data_dir/row["sample_path"]
    assert sample.exists()
    assert sample.stat().st_size == row["sample_size_bytes"] == row["value_count"]*row["element_size_bytes"]
print(f"verified_samples={len(rows)} event_rows={stats['rows_total']['events']} match_rows={stats['rows_total']['matches']}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"

