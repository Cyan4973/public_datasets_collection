#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="launchlibrary_upcoming"
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
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
obj=json.load(open(download_dir/'launchlibrary_upcoming.json',encoding='utf-8'))
def ts(s): return calendar.timegm(datetime.strptime(s[:19],'%Y-%m-%dT%H:%M:%S').utctimetuple())
meta={'launchlib_net':['uint',32,'I'],'launchlib_window_start':['uint',32,'I'],'launchlib_window_end':['uint',32,'I'],'launchlib_probability':['uint',8,'B'],'launchlib_webcast_live':['uint',8,'B'],'launchlib_agency_attempt_count':['uint',16,'H'],'launchlib_pad_attempt_count':['uint',16,'H'],'launchlib_status_id':['uint',8,'B']}
vals={sid:[] for sid in meta}; skipped=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for row in obj['results']:
    try:
        vals['launchlib_net'].append(ts(row['net']))
        vals['launchlib_window_start'].append(ts(row['window_start']))
        vals['launchlib_window_end'].append(ts(row['window_end']))
        vals['launchlib_probability'].append(int(row.get('probability') or 0))
        vals['launchlib_webcast_live'].append(1 if row.get('webcast_live') else 0)
        vals['launchlib_agency_attempt_count'].append(int(row.get('agency_launch_attempt_count') or 0))
        vals['launchlib_pad_attempt_count'].append(int(row.get('pad_launch_attempt_count') or 0))
        vals['launchlib_status_id'].append(int((row.get('status') or {}).get('id') or 0))
    except Exception:
        skipped += 1
rows=[]
for sid,(kind,bits,code) in meta.items():
    values=vals[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open('wb') as fh: fh.write(struct.pack('<'+code*len(values), *values))
    rows.append({'dataset_id':'launchlibrary_upcoming','series_id':sid,'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':kind,'bit_width':bits,'endianness':'little','element_size_bytes':bits//8,'sample_size_bytes':out.stat().st_size,'value_count':len(values)})
(filter_dir/'ingest_stats.json').write_text(json.dumps({'dataset_id':'launchlibrary_upcoming','rows_total':len(obj['results']),'rows_skipped':skipped},indent=2,sort_keys=True)+ '\n',encoding='utf-8')
with (index_dir/'samples.jsonl').open('w',encoding='utf-8') as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+'\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
