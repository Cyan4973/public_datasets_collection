#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="sec_submissions_recent"
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
import array, csv, json, os, shutil
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
companies=[('aapl','0000320193'),('msft','0000789019')]
series_defs=[
 {'series_id':'sec_submission_form_length','array_type':'H','numeric_kind':'uint','bit_width':16,'endianness':'little','element_size_bytes':2},
 {'series_id':'sec_submission_size','array_type':'I','numeric_kind':'uint','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'sec_submission_xbrl_flag','array_type':'B','numeric_kind':'uint','bit_width':8,'endianness':'little','element_size_bytes':1},
 {'series_id':'sec_submission_inline_xbrl_flag','array_type':'B','numeric_kind':'uint','bit_width':8,'endianness':'little','element_size_bytes':1},
 {'series_id':'sec_submission_year','array_type':'H','numeric_kind':'uint','bit_width':16,'endianness':'little','element_size_bytes':2},
]
for s in series_defs:
 d=samples_dir/s['series_id']
 if d.exists(): shutil.rmtree(d)
 d.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True); index_dir.mkdir(parents=True, exist_ok=True)
records=[]
with (filter_dir/'company_stats.tsv').open('w', encoding='utf-8', newline='') as f:
 w=csv.writer(f, delimiter='\t'); w.writerow(['company_id','cik','row_count','kept_count','skipped_count'])
 for company_id,cik in companies:
  recent=json.load(open(download_dir/f'{company_id}.json', encoding='utf-8'))['filings']['recent']
  row_count=len(recent.get('accessionNumber',[])); kept=0; skipped=0
  vals={s['series_id']:[] for s in series_defs}
  for form,size,isxbrl,isinline,filed in zip(recent.get('form',[]), recent.get('size',[]), recent.get('isXBRL',[]), recent.get('isInlineXBRL',[]), recent.get('filingDate',[])):
   try:
    vals['sec_submission_form_length'].append(len(form or ''))
    vals['sec_submission_size'].append(int(size))
    vals['sec_submission_xbrl_flag'].append(1 if int(isxbrl) else 0)
    vals['sec_submission_inline_xbrl_flag'].append(1 if int(isinline) else 0)
    vals['sec_submission_year'].append(int((filed or '')[:4]))
    kept += 1
   except Exception:
    skipped += 1
  w.writerow([company_id,cik,row_count,kept,skipped])
  for s in series_defs:
   arr=array.array(s['array_type'], vals[s['series_id']])
   if arr.itemsize > 1 and os.sys.byteorder != 'little': arr.byteswap()
   out=samples_dir/s['series_id']/f'{company_id}.bin'
   with out.open('wb') as fh: fh.write(arr.tobytes())
   records.append({'dataset_id':'sec_submissions_recent','series_id':s['series_id'],'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':s['numeric_kind'],'bit_width':s['bit_width'],'endianness':s['endianness'],'element_size_bytes':s['element_size_bytes'],'sample_size_bytes':out.stat().st_size,'value_count':len(vals[s['series_id']]),'company_id':company_id,'cik':cik})
with (index_dir/'samples.jsonl').open('w', encoding='utf-8') as fh:
 for row in records: fh.write(json.dumps(row, sort_keys=True)+'\n')
if not records: raise SystemExit('no submission samples produced')
PYB
echo "[$(date -Is)] build done dataset=$DATASET_ID"
