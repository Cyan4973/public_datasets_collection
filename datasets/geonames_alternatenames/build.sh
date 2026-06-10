#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="geonames_alternatenames"
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
import array, csv, json, os, shutil, zipfile
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
series_defs=[
 {'series_id':'geonames_altname_id_u32','array_type':'i','numeric_kind':'int','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'geonames_altname_geoname_id_u32','array_type':'i','numeric_kind':'int','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'geonames_altname_iso_lang_length_u8','array_type':'B','numeric_kind':'uint','bit_width':8,'endianness':'little','element_size_bytes':1},
 {'series_id':'geonames_altname_text_length_u16','array_type':'H','numeric_kind':'uint','bit_width':16,'endianness':'little','element_size_bytes':2},
 {'series_id':'geonames_altname_is_preferred_u8','array_type':'B','numeric_kind':'uint','bit_width':8,'endianness':'little','element_size_bytes':1},
 {'series_id':'geonames_altname_is_short_u8','array_type':'B','numeric_kind':'uint','bit_width':8,'endianness':'little','element_size_bytes':1},
]
for s in series_defs:
 d=samples_dir/s['series_id']
 if d.exists(): shutil.rmtree(d)
 d.mkdir(parents=True, exist_ok=True)
vals={s['series_id']:[] for s in series_defs}
row_count=0; kept=0; skipped=0
with zipfile.ZipFile(download_dir/'alternateNames.zip') as zf:
    with zf.open('alternateNames.txt') as fh:
        for raw in fh:
            row_count += 1
            try:
                parts=raw.decode('utf-8').rstrip('\n').split('\t')
                alt_id=int(parts[0]); geoname_id=int(parts[1]); iso_len=len(parts[2]); text_len=len(parts[3]); preferred=1 if parts[4] == '1' else 0; short=1 if len(parts) > 5 and parts[5] == '1' else 0
            except Exception:
                skipped += 1
                continue
            vals['geonames_altname_id_u32'].append(alt_id)
            vals['geonames_altname_geoname_id_u32'].append(geoname_id)
            vals['geonames_altname_iso_lang_length_u8'].append(iso_len)
            vals['geonames_altname_text_length_u16'].append(text_len)
            vals['geonames_altname_is_preferred_u8'].append(preferred)
            vals['geonames_altname_is_short_u8'].append(short)
            kept += 1
with (filter_dir/'stats.tsv').open('w', encoding='utf-8', newline='') as f:
    w=csv.writer(f, delimiter='\t'); w.writerow(['row_count','kept_count','skipped_count']); w.writerow([row_count, kept, skipped])
records=[]
for s in series_defs:
    arr=array.array(s['array_type'], vals[s['series_id']])
    if arr.itemsize > 1 and os.sys.byteorder != 'little': arr.byteswap()
    out=samples_dir/s['series_id']/'alternatenames.bin'
    with out.open('wb') as fh: fh.write(arr.tobytes())
    records.append({'dataset_id':'geonames_alternatenames','series_id':s['series_id'],'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':s['numeric_kind'],'bit_width':s['bit_width'],'endianness':s['endianness'],'element_size_bytes':s['element_size_bytes'],'sample_size_bytes':out.stat().st_size,'value_count':len(vals[s['series_id']])})
import json
with (index_dir/'samples.jsonl').open('w', encoding='utf-8') as fh:
    for row in records: fh.write(json.dumps(row, sort_keys=True)+'\n')
if kept < 1000000: raise SystemExit(f'kept too few rows: {kept}')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
