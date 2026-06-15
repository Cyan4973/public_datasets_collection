#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nih_reporter_projects"
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
import csv, json, os
from pathlib import Path
root = Path(os.environ['REPO_ROOT']) / os.environ['DATA_DIR']
rows = [json.loads(line) for line in (Path(os.environ['INDEX_DIR']) / 'samples.jsonl').read_text().splitlines() if line.strip()]
if len(rows) != 4:
    raise SystemExit(f'unexpected row count {len(rows)}')
for row in rows:
    p = root / row['sample_path']
    if not p.is_file():
        raise SystemExit(f'missing sample {row["sample_path"]}')
    if row['sample_size_bytes'] != p.stat().st_size:
        raise SystemExit(f'size mismatch {row["sample_path"]}')
    if row['value_count'] * row['element_size_bytes'] != row['sample_size_bytes']:
        raise SystemExit(f'bad sizing {row["sample_path"]}')
with open(Path(os.environ['FILTER_DIR']) / 'stats.tsv', encoding='utf-8') as f:
    stats = list(csv.DictReader(f, delimiter='\t'))
kept = int(stats[0]['kept_count'])
if kept < 100:
    raise SystemExit(f'kept too few rows {kept}')
print(f'verified_samples={len(rows)} rows_total={kept} rows_skipped={int(stats[0]["skipped_count"])}')
PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
