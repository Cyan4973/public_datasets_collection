#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="covertype_uci"
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
import csv, gzip, json, os, struct
from pathlib import Path
repo = Path(os.environ['REPO_ROOT']); data_dir = os.environ['DATA_DIR']
extract_dir = Path(os.environ['EXTRACT_DIR']); filter_dir = Path(os.environ['FILTER_DIR']); index_dir = Path(os.environ['INDEX_DIR']); samples_dir = Path(os.environ['SAMPLES_DIR'])
cols = [[] for _ in range(55)]
row_count = 0
with gzip.open(extract_dir / 'covtype.data.gz', 'rt', newline='') as fh:
    reader = csv.reader(fh)
    for row in reader:
        if len(row) != 55:
            raise SystemExit('unexpected row width')
        row_count += 1
        for i, value in enumerate(row):
            cols[i].append(int(value))
filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
(filter_dir / 'inventory.tsv').write_text(f'row_count\n{row_count}\n')
rows=[]
for i, values in enumerate(cols, start=1):
    if i == 5:
        kind, fmt, bits, size = 'int', '<h', 16, 2
    elif i <= 10:
        kind, fmt, bits, size = 'uint', '<H', 16, 2
    elif i <= 54 or i == 55:
        kind, fmt, bits, size = 'uint', '<B', 8, 1
    sid = f'cov_col_{i:02d}'
    outdir = samples_dir / sid; outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / 'series.bin'
    with out.open('wb') as fh:
        for value in values:
            fh.write(struct.pack(fmt, value))
    rows.append({'dataset_id':'covertype_uci','series_id':sid,'sample_path':str(out.relative_to(repo / data_dir)),'numeric_kind':kind,'bit_width':bits,'endianness':'little','element_size_bytes':size,'sample_size_bytes':out.stat().st_size,'value_count':len(values)})
with (index_dir / 'samples.jsonl').open('w') as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + '\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
