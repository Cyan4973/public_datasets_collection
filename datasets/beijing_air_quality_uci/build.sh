#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="beijing_air_quality_uci"
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
fields = ['year','month','day','hour','PM2.5','PM10','SO2','NO2','CO','O3','TEMP','PRES','DEWP','RAIN','WSPM']
base = extract_dir / 'PRSA_Data_20130301-20170228'
filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
rows=[]
with (filter_dir / 'inventory.tsv').open('w') as inv:
    inv.write('sample\trow_count\n')
    for station_csv in sorted(base.glob('*.csv')):
        station = station_csv.stem.replace('PRSA_Data_', '').lower()
        values = {f: [] for f in fields}
        kept = 0
        with station_csv.open(newline='') as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    parsed = {f: float(row[f]) for f in fields}
                except Exception:
                    continue
                kept += 1
                for f, v in parsed.items(): values[f].append(v)
        inv.write(f'{station}\t{kept}\n')
        for f in fields:
            sid='air_' + f.lower().replace('.','').replace('/','_')
            outdir = samples_dir / sid; outdir.mkdir(parents=True, exist_ok=True)
            out = outdir / f'{station}.bin'
            with out.open('wb') as fh:
                for v in values[f]: fh.write(struct.pack('<d', v))
            rows.append({'dataset_id':'beijing_air_quality_uci','series_id':sid,'sample_path':str(out.relative_to(repo / data_dir)),'numeric_kind':'float','bit_width':64,'endianness':'little','element_size_bytes':8,'sample_size_bytes':out.stat().st_size,'value_count':len(values[f])})
with (index_dir / 'samples.jsonl').open('w') as fh:
    for row in rows: fh.write(json.dumps(row, sort_keys=True) + '\n')

PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
