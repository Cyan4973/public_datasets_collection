#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="scryfall_default_cards"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations
import array, csv, json, os, shutil, struct
from pathlib import Path
repo_root = Path(os.environ['REPO_ROOT'])
data_root = repo_root / os.environ['DATA_DIR']
download_dir = Path(os.environ['DOWNLOAD_DIR'])
filter_dir = Path(os.environ['FILTER_DIR'])
index_dir = Path(os.environ['INDEX_DIR'])
samples_dir = Path(os.environ['SAMPLES_DIR'])
series_defs = [
    {'series_id': 'scryfall_cmc_f32', 'kind': 'float32', 'numeric_kind': 'float', 'bit_width': 32, 'endianness': 'little', 'element_size_bytes': 4},
    {'series_id': 'scryfall_edhrec_rank_u32', 'array_type': 'I', 'numeric_kind': 'uint', 'bit_width': 32, 'endianness': 'little', 'element_size_bytes': 4},
    {'series_id': 'scryfall_released_year_u16', 'array_type': 'H', 'numeric_kind': 'uint', 'bit_width': 16, 'endianness': 'little', 'element_size_bytes': 2},
    {'series_id': 'scryfall_released_month_u8', 'array_type': 'B', 'numeric_kind': 'uint', 'bit_width': 8, 'endianness': 'little', 'element_size_bytes': 1},
    {'series_id': 'scryfall_games_count_u8', 'array_type': 'B', 'numeric_kind': 'uint', 'bit_width': 8, 'endianness': 'little', 'element_size_bytes': 1},
    {'series_id': 'scryfall_color_count_u8', 'array_type': 'B', 'numeric_kind': 'uint', 'bit_width': 8, 'endianness': 'little', 'element_size_bytes': 1},
    {'series_id': 'scryfall_color_identity_count_u8', 'array_type': 'B', 'numeric_kind': 'uint', 'bit_width': 8, 'endianness': 'little', 'element_size_bytes': 1},
]
for s in series_defs:
    d = samples_dir / s['series_id']
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
rows = json.load(open(download_dir / 'cards.json', encoding='utf-8'))['data']
vals = {s['series_id']: [] for s in series_defs}
row_count = len(rows)
kept = 0
skipped = 0
for row in rows:
    try:
        cmc = float(row['cmc'])
        released = str(row['released_at'])
        year = int(released[:4])
        month = int(released[5:7])
        edhrec = int(row.get('edhrec_rank') or 0)
        color_count = len(row.get('colors', []))
        color_identity_count = len(row.get('color_identity', []))
        games_count = len(row.get('games', []))
    except Exception:
        skipped += 1
        continue
    vals['scryfall_cmc_f32'].append(cmc)
    vals['scryfall_edhrec_rank_u32'].append(edhrec)
    vals['scryfall_released_year_u16'].append(year)
    vals['scryfall_released_month_u8'].append(month)
    vals['scryfall_games_count_u8'].append(games_count)
    vals['scryfall_color_count_u8'].append(color_count)
    vals['scryfall_color_identity_count_u8'].append(color_identity_count)
    kept += 1
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)
with (filter_dir / 'stats.tsv').open('w', encoding='utf-8', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['row_count', 'kept_count', 'skipped_count'])
    w.writerow([row_count, kept, skipped])
records = []
for s in series_defs:
    out = samples_dir / s['series_id'] / 'cards.bin'
    if s.get('kind') == 'float32':
        with out.open('wb') as fh:
            for value in vals[s['series_id']]:
                fh.write(struct.pack('<f', value))
    else:
        arr = array.array(s['array_type'], vals[s['series_id']])
        if arr.itemsize > 1 and os.sys.byteorder != 'little':
            arr.byteswap()
        with out.open('wb') as fh:
            fh.write(arr.tobytes())
    records.append({
        'dataset_id': 'scryfall_default_cards',
        'series_id': s['series_id'],
        'sample_path': out.relative_to(data_root).as_posix(),
        'numeric_kind': s['numeric_kind'],
        'bit_width': s['bit_width'],
        'endianness': s['endianness'],
        'element_size_bytes': s['element_size_bytes'],
        'sample_size_bytes': out.stat().st_size,
        'value_count': len(vals[s['series_id']]),
    })
with (index_dir / 'samples.jsonl').open('w', encoding='utf-8') as fh:
    for row in records:
        fh.write(json.dumps(row, sort_keys=True) + '\n')
if kept < 150:
    raise SystemExit(f'kept too few rows: {kept}')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
