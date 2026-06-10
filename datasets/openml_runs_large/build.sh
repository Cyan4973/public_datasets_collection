#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openml_runs_large"
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
import array, csv, json, os, shutil
from datetime import datetime, timezone
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
series_defs=[
 {'series_id':'openml_run_id_u32','array_type':'I','numeric_kind':'uint','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'openml_task_id_u32','array_type':'I','numeric_kind':'uint','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'openml_setup_id_u32','array_type':'I','numeric_kind':'uint','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'openml_flow_id_u32','array_type':'I','numeric_kind':'uint','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'openml_uploader_u32','array_type':'I','numeric_kind':'uint','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'openml_upload_timestamp_u64','array_type':'Q','numeric_kind':'uint','bit_width':64,'endianness':'little','element_size_bytes':8},
]
for s in series_defs:
 d=samples_dir/s['series_id']
 if d.exists(): shutil.rmtree(d)
 d.mkdir(parents=True, exist_ok=True)
rows=json.load(open(download_dir/'runs.json', encoding='utf-8'))['runs']['run']
vals={s['series_id']:[] for s in series_defs}
row_count=len(rows); kept=0; skipped=0
for row in rows:
    try:
        run_id=int(row['run_id']); task_id=int(row['task_id']); setup_id=int(row['setup_id']); flow_id=int(row['flow_id']); uploader=int(row['uploader'])
        upload=int(datetime.strptime(row['upload_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        skipped += 1
        continue
    vals['openml_run_id_u32'].append(run_id)
    vals['openml_task_id_u32'].append(task_id)
    vals['openml_setup_id_u32'].append(setup_id)
    vals['openml_flow_id_u32'].append(flow_id)
    vals['openml_uploader_u32'].append(uploader)
    vals['openml_upload_timestamp_u64'].append(upload)
    kept += 1
with (filter_dir/'stats.tsv').open('w', encoding='utf-8', newline='') as f:
    w=csv.writer(f, delimiter='\t'); w.writerow(['row_count','kept_count','skipped_count']); w.writerow([row_count, kept, skipped])
records=[]
for s in series_defs:
    arr=array.array(s['array_type'], vals[s['series_id']])
    if arr.itemsize > 1 and os.sys.byteorder != 'little': arr.byteswap()
    out=samples_dir/s['series_id']/'runs.bin'
    with out.open('wb') as fh: fh.write(arr.tobytes())
    records.append({'dataset_id':'openml_runs_large','series_id':s['series_id'],'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':s['numeric_kind'],'bit_width':s['bit_width'],'endianness':s['endianness'],'element_size_bytes':s['element_size_bytes'],'sample_size_bytes':out.stat().st_size,'value_count':len(vals[s['series_id']])})
with (index_dir/'samples.jsonl').open('w', encoding='utf-8') as fh:
    for row in records: fh.write(json.dumps(row, sort_keys=True)+'\n')
if kept < 500: raise SystemExit(f'kept too few rows: {kept}')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
