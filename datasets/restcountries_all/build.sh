#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="restcountries_all"
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
python3 - <<'PYB'
from __future__ import annotations
import json, os, shutil, struct
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
items=json.load(open(download_dir/'restcountries_all.json', encoding='utf-8'))
meta={
 'restcountries_population': ('uint', 64, 'Q'),
 'restcountries_area': ('float', 32, 'f'),
 'restcountries_latitude': ('float', 32, 'f'),
 'restcountries_longitude': ('float', 32, 'f'),
 'restcountries_timezone_count': ('uint', 8, 'B'),
 'restcountries_capital_latitude': ('float', 32, 'f'),
 'restcountries_capital_longitude': ('float', 32, 'f'),
}
vals={sid:[] for sid in meta}; skipped=0
for sid in vals:
 d=samples_dir/sid
 if d.exists(): shutil.rmtree(d)
 d.mkdir(parents=True, exist_ok=True)
for row in items:
 try:
  latlng=row['latlng']
  cap=row['capitalInfo']['latlng']
  vals['restcountries_population'].append(int(row['population']))
  vals['restcountries_area'].append(float(row['area']))
  vals['restcountries_latitude'].append(float(latlng[0]))
  vals['restcountries_longitude'].append(float(latlng[1]))
  vals['restcountries_timezone_count'].append(len(row.get('timezones') or []))
  vals['restcountries_capital_latitude'].append(float(cap[0]))
  vals['restcountries_capital_longitude'].append(float(cap[1]))
 except Exception:
  skipped += 1
rows=[]
for sid,(kind,bits,code) in meta.items():
 values=vals[sid]
 out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
 with out.open('wb') as fh: fh.write(struct.pack('<' + code*len(values), *values))
 rows.append({'dataset_id':'restcountries_all','series_id':sid,'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':kind,'bit_width':bits,'endianness':'little','element_size_bytes':bits//8,'sample_size_bytes':out.stat().st_size,'value_count':len(values)})
(filter_dir/'ingest_stats.json').write_text(json.dumps({'dataset_id':'restcountries_all','rows_total':len(items),'rows_skipped':skipped}, indent=2, sort_keys=True)+'\n', encoding='utf-8')
with (index_dir/'samples.jsonl').open('w', encoding='utf-8') as fh:
 for row in rows: fh.write(json.dumps(row, sort_keys=True)+'\n')
PYB
echo "[$(date -Is)] build done dataset=$DATASET_ID"
