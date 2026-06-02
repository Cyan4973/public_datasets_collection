#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bike_sharing_uci"
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
from pathlib import Path
repo = Path(os.environ['REPO_ROOT']); data_dir = os.environ['DATA_DIR']
extract_dir = Path(os.environ['EXTRACT_DIR']); filter_dir = Path(os.environ['FILTER_DIR']); index_dir = Path(os.environ['INDEX_DIR']); samples_dir = Path(os.environ['SAMPLES_DIR'])
cols = ['season','yr','mnth','hr','holiday','weekday','workingday','weathersit','temp','atemp','hum','windspeed','casual','registered','cnt']
values = {c: [] for c in cols}
with (extract_dir / 'hour.csv').open(newline='') as fh:
    reader = csv.DictReader(fh)
    row_count = 0
    for row in reader:
        row_count += 1
        for c in cols: values[c].append(float(row[c]))
filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
(filter_dir / 'inventory.tsv').write_text(f'sample\trow_count\nhour\t{row_count}\n')
rows=[]
for c in cols:
    sid='bike_' + c
    outdir = samples_dir / sid; outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / 'hour.bin'
    with out.open('wb') as fh:
        for v in values[c]: fh.write(struct.pack('<d', v))
    rows.append({'dataset_id':'bike_sharing_uci','series_id':sid,'sample_path':str(out.relative_to(repo / data_dir)),'numeric_kind':'float','bit_width':64,'endianness':'little','element_size_bytes':8,'sample_size_bytes':out.stat().st_size,'value_count':len(values[c])})
with (index_dir / 'samples.jsonl').open('w') as fh:
    for row in rows: fh.write(json.dumps(row, sort_keys=True) + '\n')

PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
