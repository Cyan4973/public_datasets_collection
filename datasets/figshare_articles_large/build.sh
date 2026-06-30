#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="figshare_articles_large"
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
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
export FIGSHARE_ARTICLES_LARGE_MIN_RETAINED_RECORDS="${FIGSHARE_ARTICLES_LARGE_MIN_RETAINED_RECORDS:-17000}"
python3 - <<'PY'
from __future__ import annotations
import array, csv, json, os, shutil
from datetime import datetime, timezone
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
min_retained=int(os.environ['FIGSHARE_ARTICLES_LARGE_MIN_RETAINED_RECORDS'])
series_defs=[
 {'series_id':'figshare_id_u32','array_type':'I','numeric_kind':'uint','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'figshare_defined_type_u16','array_type':'H','numeric_kind':'uint','bit_width':16,'endianness':'little','element_size_bytes':2},
 {'series_id':'figshare_group_id_u32','array_type':'I','numeric_kind':'uint','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'figshare_published_timestamp_i64','array_type':'q','numeric_kind':'int','bit_width':64,'endianness':'little','element_size_bytes':8},
 {'series_id':'figshare_created_timestamp_i64','array_type':'q','numeric_kind':'int','bit_width':64,'endianness':'little','element_size_bytes':8},
 {'series_id':'figshare_modified_timestamp_i64','array_type':'q','numeric_kind':'int','bit_width':64,'endianness':'little','element_size_bytes':8},
]
for s in series_defs:
 d=samples_dir/s['series_id']
 if d.exists(): shutil.rmtree(d)
 d.mkdir(parents=True, exist_ok=True)
rows=json.load(open(download_dir/'articles.json', encoding='utf-8'))
vals={s['series_id']:[] for s in series_defs}
row_count=len(rows); kept=0; skipped=0
for row in rows:
    try:
        parsed = {
            'figshare_id_u32': int(row['id']),
            'figshare_defined_type_u16': int(row['defined_type']),
            'figshare_group_id_u32': int(row['group_id']),
            'figshare_published_timestamp_i64': int(datetime.fromisoformat(row['published_date'].replace('Z','+00:00')).timestamp()),
            'figshare_created_timestamp_i64': int(datetime.fromisoformat(row['created_date'].replace('Z','+00:00')).timestamp()),
            'figshare_modified_timestamp_i64': int(datetime.fromisoformat(row['modified_date'].replace('Z','+00:00')).timestamp()),
        }
    except Exception:
        skipped += 1
        continue
    for sid, value in parsed.items():
        vals[sid].append(value)
    kept += 1
if kept < min_retained:
    raise SystemExit(f'kept too few rows: {kept} < FIGSHARE_ARTICLES_LARGE_MIN_RETAINED_RECORDS={min_retained}')
if len({len(values) for values in vals.values()}) != 1:
    raise SystemExit('series length mismatch after filtering')
with (filter_dir/'stats.tsv').open('w', encoding='utf-8', newline='') as f:
    w=csv.writer(f, delimiter='\t'); w.writerow(['row_count','kept_count','skipped_count']); w.writerow([row_count, kept, skipped])
records=[]
for s in series_defs:
    arr=array.array(s['array_type'], vals[s['series_id']])
    if arr.itemsize > 1 and os.sys.byteorder != 'little': arr.byteswap()
    out=samples_dir/s['series_id']/'articles.bin'
    with out.open('wb') as fh: fh.write(arr.tobytes())
    records.append({'dataset_id':'figshare_articles_large','series_id':s['series_id'],'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':s['numeric_kind'],'bit_width':s['bit_width'],'endianness':s['endianness'],'element_size_bytes':s['element_size_bytes'],'sample_size_bytes':out.stat().st_size,'value_count':len(vals[s['series_id']])})
with (index_dir/'samples.jsonl').open('w', encoding='utf-8') as fh:
    for row in records: fh.write(json.dumps(row, sort_keys=True)+'\n')
if sum(row['value_count'] for row in records) < 100000:
    raise SystemExit('below large-repair value target: expected at least 100000 primary values')
for sid, values in vals.items():
    if min(values) == max(values):
        raise SystemExit(f'constant sample: {sid}')
print(f'built samples={len(records)} retained_records={kept} values={sum(row["value_count"] for row in records)} bytes={sum(row["sample_size_bytes"] for row in records)} skipped={skipped}')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
