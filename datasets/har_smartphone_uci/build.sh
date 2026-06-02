#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="har_smartphone_uci"
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
import json, os, struct
from pathlib import Path
repo = Path(os.environ['REPO_ROOT']); data_dir = os.environ['DATA_DIR']
extract_dir = Path(os.environ['EXTRACT_DIR']); filter_dir = Path(os.environ['FILTER_DIR']); index_dir = Path(os.environ['INDEX_DIR']); samples_dir = Path(os.environ['SAMPLES_DIR'])
base = extract_dir / 'UCI HAR Dataset'
mapping = {
    'har_total_acc_x': 'total_acc_x', 'har_total_acc_y': 'total_acc_y', 'har_total_acc_z': 'total_acc_z',
    'har_body_acc_x': 'body_acc_x', 'har_body_acc_y': 'body_acc_y', 'har_body_acc_z': 'body_acc_z',
    'har_body_gyro_x': 'body_gyro_x', 'har_body_gyro_y': 'body_gyro_y', 'har_body_gyro_z': 'body_gyro_z',
}
filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
rows=[]
with (filter_dir / 'inventory.tsv').open('w') as inv:
    inv.write('series\tsplit\tvalue_count\n')
    for sid, stem in mapping.items():
        outdir = samples_dir / sid; outdir.mkdir(parents=True, exist_ok=True)
        for split in ('train','test'):
            path = base / split / 'Inertial Signals' / f'{stem}_{split}.txt'
            values = []
            for line in path.read_text().splitlines():
                parts = [p for p in line.strip().split() if p]
                values.extend(float(p) for p in parts)
            out = outdir / f'{split}.bin'
            with out.open('wb') as fh:
                for value in values:
                    fh.write(struct.pack('<d', value))
            inv.write(f'{sid}\t{split}\t{len(values)}\n')
            rows.append({'dataset_id':'har_smartphone_uci','series_id':sid,'sample_path':str(out.relative_to(repo / data_dir)),'numeric_kind':'float','bit_width':64,'endianness':'little','element_size_bytes':8,'sample_size_bytes':out.stat().st_size,'value_count':len(values)})
with (index_dir / 'samples.jsonl').open('w') as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + '\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
