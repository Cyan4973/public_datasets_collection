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
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
INDEX_PATH="$INDEX_DIR/samples.jsonl" EXTRACT_DIR="$EXTRACT_DIR" REPO_ROOT="$REPO_ROOT" DATA_DIR="$DATA_DIR" python3 - <<'PY'

import csv, json, os
from pathlib import Path
index_path = Path(os.environ['INDEX_PATH'])
extract_dir = Path(os.environ['EXTRACT_DIR'])
repo_root = Path(os.environ['REPO_ROOT'])
data_dir = os.environ['DATA_DIR']

series_defs = [
    {'col': 'temp',       'kind': 'float', 'bit_width': 32, 'size': 4},
    {'col': 'atemp',      'kind': 'float', 'bit_width': 32, 'size': 4},
    {'col': 'hum',        'kind': 'float', 'bit_width': 32, 'size': 4},
    {'col': 'windspeed',  'kind': 'float', 'bit_width': 32, 'size': 4},
    {'col': 'weathersit', 'kind': 'uint',  'bit_width': 8,  'size': 1},
    {'col': 'casual',     'kind': 'uint',  'bit_width': 16, 'size': 2},
    {'col': 'registered', 'kind': 'uint',  'bit_width': 16, 'size': 2},
    {'col': 'cnt',        'kind': 'uint',  'bit_width': 16, 'size': 2},
]
# Calendar / calendar-derived columns that must NOT appear in the output.
excluded = ['instant', 'dteday', 'season', 'yr', 'mnth', 'hr', 'holiday', 'weekday', 'workingday']

# Independently recompute row count and re-check that every integer value fits its width.
with (extract_dir / 'hour.csv').open(newline='') as fh:
    reader = csv.DictReader(fh)
    n = 0
    for row in reader:
        n += 1
        for d in series_defs:
            if d['kind'] == 'uint':
                iv = int(row[d['col']])
                hi = (1 << d['bit_width']) - 1
                if iv < 0 or iv > hi:
                    raise SystemExit(f"column {d['col']} value {iv} out of u{d['bit_width']} range")

if not index_path.exists():
    raise SystemExit(f'missing index: {index_path}')
idx = {}
for line in index_path.read_text().splitlines():
    if not line.strip():
        continue
    o = json.loads(line)
    idx[o['series_id']] = o

expected = {'bike_' + d['col'] for d in series_defs}
if set(idx) != expected:
    raise SystemExit(f'series set mismatch: index={sorted(idx)} expected={sorted(expected)}')
leaked = [c for c in excluded if ('bike_' + c) in idx]
if leaked:
    raise SystemExit(f'calendar columns leaked into output: {leaked}')

for d in series_defs:
    o = idx['bike_' + d['col']]
    if o['numeric_kind'] != d['kind'] or o['bit_width'] != d['bit_width'] or o['element_size_bytes'] != d['size']:
        raise SystemExit(f"width/kind mismatch for {d['col']}: {o}")
    if o['value_count'] != n:
        raise SystemExit(f"value_count mismatch for {d['col']}: {o['value_count']} != {n}")
    p = repo_root / data_dir / o['sample_path']
    if not p.exists():
        raise SystemExit(f'missing sample: {p}')
    size = p.stat().st_size
    if size != n * d['size']:
        raise SystemExit(f"size mismatch for {d['col']}: {size} != {n * d['size']}")
    if size != o['sample_size_bytes']:
        raise SystemExit(f"index size mismatch for {d['col']}")

print(f'verified rows={n} series={len(idx)} (calendar columns excluded)')

PY
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
