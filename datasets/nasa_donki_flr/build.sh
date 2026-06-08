#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_donki_flr"
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
items=json.load(open(download_dir/'nasa_donki_flr.json', encoding='utf-8'))
meta={
 'donki_flr_active_region_num': ('uint', 32, 'I'),
 'donki_flr_class_magnitude': ('float', 32, 'f'),
 'donki_flr_begin_year': ('uint', 16, 'H'),
 'donki_flr_peak_year': ('uint', 16, 'H'),
 'donki_flr_end_year': ('uint', 16, 'H'),
 'donki_flr_instrument_count': ('uint', 8, 'B'),
}
vals={sid:[] for sid in meta}; skipped=0
for sid in vals:
 d=samples_dir/sid
 if d.exists(): shutil.rmtree(d)
 d.mkdir(parents=True, exist_ok=True)
for row in items:
 try:
  cls=row['classType']
  mag=float(cls[1:])
  vals['donki_flr_active_region_num'].append(int(row['activeRegionNum'] or 0))
  vals['donki_flr_class_magnitude'].append(mag)
  vals['donki_flr_begin_year'].append(int((row['beginTime'] or '')[:4]))
  vals['donki_flr_peak_year'].append(int((row['peakTime'] or '')[:4]))
  vals['donki_flr_end_year'].append(int((row['endTime'] or '')[:4]))
  vals['donki_flr_instrument_count'].append(len(row.get('instruments') or []))
 except Exception:
  skipped += 1
rows=[]
for sid,(kind,bits,code) in meta.items():
 values=vals[sid]
 out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
 with out.open('wb') as fh: fh.write(struct.pack('<' + code*len(values), *values))
 rows.append({'dataset_id':'nasa_donki_flr','series_id':sid,'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':kind,'bit_width':bits,'endianness':'little','element_size_bytes':bits//8,'sample_size_bytes':out.stat().st_size,'value_count':len(values)})
(filter_dir/'ingest_stats.json').write_text(json.dumps({'dataset_id':'nasa_donki_flr','rows_total':len(items),'rows_skipped':skipped}, indent=2, sort_keys=True)+'\n', encoding='utf-8')
with (index_dir/'samples.jsonl').open('w', encoding='utf-8') as fh:
 for row in rows: fh.write(json.dumps(row, sort_keys=True)+'\n')
PYB
echo "[$(date -Is)] build done dataset=$DATASET_ID"
