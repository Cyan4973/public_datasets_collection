#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="fsdd_spoken_digits"
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

import json, os, wave
from pathlib import Path
repo = Path(os.environ['REPO_ROOT']); data_dir = os.environ['DATA_DIR']
extract_dir = Path(os.environ['EXTRACT_DIR']); filter_dir = Path(os.environ['FILTER_DIR']); index_dir = Path(os.environ['INDEX_DIR']); samples_dir = Path(os.environ['SAMPLES_DIR'])
outdir = samples_dir / 'fsdd_pcm16'; outdir.mkdir(parents=True, exist_ok=True); filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
rows=[]
with (filter_dir / 'inventory.tsv').open('w') as inv:
    inv.write('sample\tframes\n')
    for wav_path in sorted((extract_dir / 'free-spoken-digit-dataset-master' / 'recordings').glob('*.wav')):
        with wave.open(str(wav_path), 'rb') as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise SystemExit(f'unexpected wav format: {wav_path}')
            frames = wav.getnframes()
            payload = wav.readframes(frames)
        out = outdir / f'{wav_path.stem}.bin'
        out.write_bytes(payload)
        inv.write(f'{wav_path.stem}\t{frames}\n')
        rows.append({'dataset_id':'fsdd_spoken_digits','series_id':'fsdd_pcm16','sample_path':str(out.relative_to(repo / data_dir)),'numeric_kind':'int','bit_width':16,'endianness':'little','element_size_bytes':2,'sample_size_bytes':len(payload),'value_count':frames})
with (index_dir / 'samples.jsonl').open('w') as fh:
    for row in rows: fh.write(json.dumps(row, sort_keys=True) + '\n')

PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
