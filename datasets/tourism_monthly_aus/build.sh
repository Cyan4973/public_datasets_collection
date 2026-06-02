#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tourism_monthly_aus"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR EXTRACT_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
import csv, json, os, struct
from collections import defaultdict
from pathlib import Path
repo = Path(os.environ['REPO_ROOT']); data_dir = os.environ['DATA_DIR']
download_dir = Path(os.environ['DOWNLOAD_DIR']); filter_dir = Path(os.environ['FILTER_DIR']); index_dir = Path(os.environ['INDEX_DIR']); samples_dir = Path(os.environ['SAMPLES_DIR'])
series = defaultdict(lambda: {'tourism_cpi': [], 'tourism_inflation_rate': []})
with (download_dir / 'data.csv').open(newline='') as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        try:
            uid = row['unique_id']
            cpi = float(row['CPI'])
            inf = float(row['Inflation_Rate'])
        except Exception:
            continue
        series[uid]['tourism_cpi'].append(cpi)
        series[uid]['tourism_inflation_rate'].append(inf)
filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
rows=[]
with (filter_dir / 'inventory.tsv').open('w') as inv:
    inv.write('unique_id\tvalue_count\n')
    for uid, vals in sorted(series.items()):
        inv.write(f'{uid}\t{len(vals["tourism_cpi"])}\n')
        slug = uid.replace('/', '_')
        for sid in ('tourism_cpi','tourism_inflation_rate'):
            outdir = samples_dir / sid; outdir.mkdir(parents=True, exist_ok=True)
            out = outdir / f'{slug}.bin'
            with out.open('wb') as fh:
                for value in vals[sid]:
                    fh.write(struct.pack('<d', value))
            rows.append({'dataset_id':'tourism_monthly_aus','series_id':sid,'sample_path':str(out.relative_to(repo / data_dir)),'numeric_kind':'float','bit_width':64,'endianness':'little','element_size_bytes':8,'sample_size_bytes':out.stat().st_size,'value_count':len(vals[sid])})
with (index_dir / 'samples.jsonl').open('w') as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + '\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
