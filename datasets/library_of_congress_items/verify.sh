#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="library_of_congress_items"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
mkdir -p "$LOG_DIR" "$FILTER_DIR" "$INDEX_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
export REPO_ROOT DATA_DIR FILTER_DIR INDEX_DIR
python3 - <<'PY'
import json, os
from pathlib import Path
root=Path(os.environ["REPO_ROOT"]) / os.environ["DATA_DIR"]
rows=[json.loads(line) for line in (Path(os.environ["INDEX_DIR"])/"samples.jsonl").read_text().splitlines() if line.strip()]
stats=json.loads((Path(os.environ["FILTER_DIR"])/"ingest_stats.json").read_text())
if len(rows) != 5: raise SystemExit(f"unexpected row count {len(rows)}")
for row in rows:
    if not (root/row["sample_path"]).is_file(): raise SystemExit(f"missing sample {row['sample_path']}")
print(f"verified_samples={len(rows)} rows_total={stats['rows_total']} rows_skipped={stats['rows_skipped']}")
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
