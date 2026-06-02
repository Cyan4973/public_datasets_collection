#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gas_sensor_array_drift_uci"
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
features = [[] for _ in range(128)]
labels = []
row_count = 0
for path in sorted((extract_dir / 'Dataset').glob('batch*.dat')):
    for line in path.read_text().splitlines():
        parts = [p for p in line.strip().split() if p]
        if len(parts) != 129:
            raise SystemExit('unexpected row width')
        row_count += 1
        labels.append(int(parts[0]))
        for token in parts[1:]:
            idx_str, value_str = token.split(':', 1)
            idx = int(idx_str) - 1
            features[idx].append(float(value_str))
filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
(filter_dir / 'inventory.tsv').write_text(f'row_count\n{row_count}\n')
rows=[]
label_dir = samples_dir / 'gas_label'; label_dir.mkdir(parents=True, exist_ok=True)
label_out = label_dir / 'series.bin'
with label_out.open('wb') as fh:
    for value in labels:
        fh.write(struct.pack('<B', value))
rows.append({'dataset_id':'gas_sensor_array_drift_uci','series_id':'gas_label','sample_path':str(label_out.relative_to(repo / data_dir)),'numeric_kind':'uint','bit_width':8,'endianness':'little','element_size_bytes':1,'sample_size_bytes':label_out.stat().st_size,'value_count':len(labels)})
for idx, values in enumerate(features, start=1):
    sid = f'gas_feat_{idx:03d}'
    outdir = samples_dir / sid; outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / 'series.bin'
    with out.open('wb') as fh:
        for value in values:
            fh.write(struct.pack('<d', value))
    rows.append({'dataset_id':'gas_sensor_array_drift_uci','series_id':sid,'sample_path':str(out.relative_to(repo / data_dir)),'numeric_kind':'float','bit_width':64,'endianness':'little','element_size_bytes':8,'sample_size_bytes':out.stat().st_size,'value_count':len(values)})
with (index_dir / 'samples.jsonl').open('w') as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + '\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
