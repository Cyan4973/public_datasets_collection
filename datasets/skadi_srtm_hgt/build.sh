#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="skadi_srtm_hgt"
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

import gzip, json, os, struct
from pathlib import Path
repo = Path(os.environ['REPO_ROOT']); data_dir = os.environ['DATA_DIR']
download_dir = Path(os.environ['DOWNLOAD_DIR']); filter_dir = Path(os.environ['FILTER_DIR']); index_dir = Path(os.environ['INDEX_DIR']); samples_dir = Path(os.environ['SAMPLES_DIR'])
filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
outdir = samples_dir / 'skadi_elevation'; outdir.mkdir(parents=True, exist_ok=True)
raw = gzip.decompress((download_dir / 'N37W122.hgt.gz').read_bytes())
if len(raw) != 3601 * 3601 * 2:
    raise SystemExit(f'unexpected tile size: {len(raw)}')
vals = struct.unpack('>' + 'h' * (3601 * 3601), raw)
rows=[]
with (filter_dir / 'inventory.tsv').open('w') as inv:
    inv.write('sample\trow_start\trow_count\n')
    for row_start in range(0, 3601, 54):
        row_count = min(54, 3601 - row_start)
        chunk = vals[row_start * 3601:(row_start + row_count) * 3601]
        out = outdir / f'rows_{row_start:04d}_{row_start + row_count - 1:04d}.bin'
        with out.open('wb') as fh: fh.write(struct.pack('<' + 'h' * len(chunk), *chunk))
        inv.write(f'{out.stem}\t{row_start}\t{row_count}\n')
        rows.append({'dataset_id':'skadi_srtm_hgt','series_id':'skadi_elevation','sample_path':str(out.relative_to(repo / data_dir)),'numeric_kind':'int','bit_width':16,'endianness':'little','element_size_bytes':2,'sample_size_bytes':out.stat().st_size,'value_count':len(chunk)})
with (index_dir / 'samples.jsonl').open('w') as fh:
    for row in rows: fh.write(json.dumps(row, sort_keys=True) + '\n')

PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
