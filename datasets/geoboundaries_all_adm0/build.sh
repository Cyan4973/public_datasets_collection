#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="geoboundaries_all_adm0"
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
import json, os, shutil, struct
from pathlib import Path
repo_root = Path(os.environ['REPO_ROOT']); data_root = repo_root / os.environ['DATA_DIR']
download_dir = Path(os.environ['DOWNLOAD_DIR']); filter_dir = Path(os.environ['FILTER_DIR']); index_dir = Path(os.environ['INDEX_DIR']); samples_dir = Path(os.environ['SAMPLES_DIR'])
obj = json.load(open(download_dir / 'geoboundaries_all_adm0.json', encoding='utf-8'))
meta = {
    'geoboundaries_boundary_year': ('uint', 16, 'H'),
    'geoboundaries_adm_unit_count': ('uint', 16, 'H'),
    'geoboundaries_mean_vertices': ('float', 32, 'f'),
    'geoboundaries_mean_perimeter_km': ('float', 32, 'f'),
    'geoboundaries_mean_area_sqkm': ('float', 32, 'f'),
}
vals = {k: [] for k in meta}; skipped = 0
for sid in vals:
    d = samples_dir / sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for row in obj:
    try:
        vals['geoboundaries_boundary_year'].append(int(float(row['boundaryYearRepresented'])))
        vals['geoboundaries_adm_unit_count'].append(int(float(row['admUnitCount'])))
        vals['geoboundaries_mean_vertices'].append(float(row['meanVertices']))
        vals['geoboundaries_mean_perimeter_km'].append(float(row['meanPerimeterLengthKM']))
        vals['geoboundaries_mean_area_sqkm'].append(float(row['meanAreaSqKM']))
    except Exception:
        skipped += 1
rows = []
for sid, (kind, bits, code) in meta.items():
    values = vals[sid]
    out = samples_dir / sid / f'{sid}_{kind}{bits}_n{len(values):06d}.bin'
    with out.open('wb') as fh:
        fh.write(struct.pack('<' + code * len(values), *values))
    rows.append({'dataset_id': 'geoboundaries_all_adm0', 'series_id': sid, 'sample_path': out.relative_to(data_root).as_posix(), 'numeric_kind': kind, 'bit_width': bits, 'endianness': 'little', 'element_size_bytes': bits // 8, 'sample_size_bytes': out.stat().st_size, 'value_count': len(values)})
(filter_dir / 'ingest_stats.json').write_text(json.dumps({'dataset_id': 'geoboundaries_all_adm0', 'rows_total': len(obj), 'rows_skipped': skipped}, indent=2, sort_keys=True) + '\n', encoding='utf-8')
with (index_dir / 'samples.jsonl').open('w', encoding='utf-8') as fh:
    for row in rows: fh.write(json.dumps(row, sort_keys=True) + '\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
