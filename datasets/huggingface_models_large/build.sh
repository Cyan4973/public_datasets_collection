#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="huggingface_models_large"
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
import calendar, json, os, shutil, struct
from datetime import datetime
from pathlib import Path
repo_root = Path(os.environ['REPO_ROOT']); data_root = repo_root / os.environ['DATA_DIR']
download_dir = Path(os.environ['DOWNLOAD_DIR']); filter_dir = Path(os.environ['FILTER_DIR']); index_dir = Path(os.environ['INDEX_DIR']); samples_dir = Path(os.environ['SAMPLES_DIR'])
obj = json.load(open(download_dir / 'huggingface_models_large.json', encoding='utf-8'))
def ts(s): return calendar.timegm(datetime.strptime(s[:19], '%Y-%m-%dT%H:%M:%S').utctimetuple())
meta = {
    'hf_model_downloads': ('uint', 64, 'Q'),
    'hf_model_likes': ('uint', 32, 'I'),
    'hf_model_trending_score': ('int', 32, 'i'),
    'hf_model_created_at': ('uint', 32, 'I'),
    'hf_model_siblings_count': ('uint', 16, 'H'),
    'hf_model_tags_count': ('uint', 16, 'H'),
    'hf_model_gated': ('uint', 8, 'B'),
    'hf_model_private': ('uint', 8, 'B'),
}
vals = {k: [] for k in meta}; skipped = 0
for sid in vals:
    d = samples_dir / sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for row in obj:
    try:
        vals['hf_model_downloads'].append(int(row['downloads']))
        vals['hf_model_likes'].append(int(row['likes']))
        vals['hf_model_trending_score'].append(int(row.get('trendingScore') or 0))
        vals['hf_model_created_at'].append(ts(row['createdAt']))
        vals['hf_model_siblings_count'].append(len(row.get('siblings') or []))
        vals['hf_model_tags_count'].append(len(row.get('tags') or []))
        vals['hf_model_gated'].append(1 if row.get('gated') else 0)
        vals['hf_model_private'].append(1 if row.get('private') else 0)
    except Exception:
        skipped += 1
rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f'{sid}_{kind}{bits}_n{len(values):06d}.bin'
    with out.open('wb') as fh:
        fh.write(struct.pack('<' + code * len(values), *values))
    rows.append({'dataset_id': 'huggingface_models_large', 'series_id': sid, 'sample_path': out.relative_to(data_root).as_posix(), 'numeric_kind': kind, 'bit_width': bits, 'endianness': 'little', 'element_size_bytes': bits // 8, 'sample_size_bytes': out.stat().st_size, 'value_count': len(values)})
(filter_dir / 'ingest_stats.json').write_text(json.dumps({'dataset_id': 'huggingface_models_large', 'rows_total': len(obj), 'rows_skipped': skipped}, indent=2, sort_keys=True) + '\n', encoding='utf-8')
with (index_dir / 'samples.jsonl').open('w', encoding='utf-8') as fh:
    for row in rows: fh.write(json.dumps(row, sort_keys=True) + '\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
