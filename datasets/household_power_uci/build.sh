#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="household_power_uci"
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
fields = ['Global_active_power','Global_reactive_power','Voltage','Global_intensity','Sub_metering_1','Sub_metering_2','Sub_metering_3']
values = {f: [] for f in fields}
total = kept = 0
with (extract_dir / 'household_power_consumption.txt').open(newline='') as fh:
    reader = csv.DictReader(fh, delimiter=';')
    for row in reader:
        total += 1
        if any(row[f] == '?' for f in fields):
            continue
        kept += 1
        for f in fields:
            if f.startswith('Sub_metering'):
                values[f].append(int(float(row[f])))
            else:
                values[f].append(float(row[f]))
filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
(filter_dir / 'inventory.tsv').write_text(f'total_rows\tkept_rows\n{total}\t{kept}\n')
mapping = {
    'Global_active_power': ('power_global_active','float',8),
    'Global_reactive_power': ('power_global_reactive','float',8),
    'Voltage': ('power_voltage','float',8),
    'Global_intensity': ('power_global_intensity','float',8),
    'Sub_metering_1': ('power_kitchen','uint',1),
    'Sub_metering_2': ('power_laundry','uint',1),
    'Sub_metering_3': ('power_hvac','uint',1),
}
rows=[]
for field, (sid, kind, size) in mapping.items():
    outdir = samples_dir / sid; outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / 'series.bin'
    with out.open('wb') as fh:
        for value in values[field]:
            if kind == 'float':
                fh.write(struct.pack('<d', value))
            else:
                fh.write(struct.pack('<B', value))
    rows.append({'dataset_id':'household_power_uci','series_id':sid,'sample_path':str(out.relative_to(repo / data_dir)),'numeric_kind':kind,'bit_width':64 if kind == 'float' else 8,'endianness':'little','element_size_bytes':size,'sample_size_bytes':out.stat().st_size,'value_count':len(values[field])})
with (index_dir / 'samples.jsonl').open('w') as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + '\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
