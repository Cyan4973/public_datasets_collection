#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nih_reporter_projects"
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
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations
import array, csv, json, os, shutil
from datetime import datetime
from pathlib import Path
repo_root = Path(os.environ['REPO_ROOT'])
data_root = repo_root / os.environ['DATA_DIR']
download_dir = Path(os.environ['DOWNLOAD_DIR'])
filter_dir = Path(os.environ['FILTER_DIR'])
index_dir = Path(os.environ['INDEX_DIR'])
samples_dir = Path(os.environ['SAMPLES_DIR'])
series_defs = [
    {'series_id': 'nih_award_amount_u64', 'array_type': 'Q', 'numeric_kind': 'uint', 'bit_width': 64, 'endianness': 'little', 'element_size_bytes': 8},
    {'series_id': 'nih_direct_cost_amount_u64', 'array_type': 'Q', 'numeric_kind': 'uint', 'bit_width': 64, 'endianness': 'little', 'element_size_bytes': 8},
    {'series_id': 'nih_project_start_year_u16', 'array_type': 'H', 'numeric_kind': 'uint', 'bit_width': 16, 'endianness': 'little', 'element_size_bytes': 2},
    {'series_id': 'nih_project_end_year_u16', 'array_type': 'H', 'numeric_kind': 'uint', 'bit_width': 16, 'endianness': 'little', 'element_size_bytes': 2},
]
for s in series_defs:
    d = samples_dir / s['series_id']
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
rows = json.load(open(download_dir / 'projects.json', encoding='utf-8'))['results']
vals = {s['series_id']: [] for s in series_defs}
row_count = len(rows)
kept = 0
skipped = 0
for row in rows:
    try:
        award = int(row['award_amount'])
        direct = int(row['direct_cost_amt'])
        fiscal_year = int(row['fiscal_year'])
        start_year = datetime.fromisoformat(row['project_start_date'].replace('Z', '+00:00')).year
        end_year = datetime.fromisoformat(row['project_end_date'].replace('Z', '+00:00')).year
    except Exception:
        skipped += 1
        continue
    vals['nih_award_amount_u64'].append(award)
    vals['nih_direct_cost_amount_u64'].append(direct)
    vals['nih_project_start_year_u16'].append(start_year)
    vals['nih_project_end_year_u16'].append(end_year)
    kept += 1
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
with (filter_dir / 'stats.tsv').open('w', encoding='utf-8', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['row_count', 'kept_count', 'skipped_count'])
    w.writerow([row_count, kept, skipped])
records = []
for s in series_defs:
    arr = array.array(s['array_type'], vals[s['series_id']])
    if arr.itemsize > 1 and os.sys.byteorder != 'little':
        arr.byteswap()
    out = samples_dir / s['series_id'] / 'projects.bin'
    with out.open('wb') as fh:
        fh.write(arr.tobytes())
    records.append({
        'dataset_id': 'nih_reporter_projects',
        'series_id': s['series_id'],
        'sample_path': out.relative_to(data_root).as_posix(),
        'numeric_kind': s['numeric_kind'],
        'bit_width': s['bit_width'],
        'endianness': s['endianness'],
        'element_size_bytes': s['element_size_bytes'],
        'sample_size_bytes': out.stat().st_size,
        'value_count': len(vals[s['series_id']]),
    })
with (index_dir / 'samples.jsonl').open('w', encoding='utf-8') as fh:
    for row in records:
        fh.write(json.dumps(row, sort_keys=True) + '\n')
if kept < 100:
    raise SystemExit(f'kept too few rows: {kept}')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
