#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="geonames_allcountries"
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
import array, csv, os, shutil, struct, zipfile
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
INT32_MIN = -(2**31)
series_defs=[
 {'series_id':'geonames_latitude_f32','kind':'float32','numeric_kind':'float','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'geonames_longitude_f32','kind':'float32','numeric_kind':'float','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'geonames_population_u64','array_type':'q','numeric_kind':'int','bit_width':64,'endianness':'little','element_size_bytes':8},
 {'series_id':'geonames_elevation_i32','array_type':'i','numeric_kind':'int','bit_width':32,'endianness':'little','element_size_bytes':4},
 {'series_id':'geonames_dem_i32','array_type':'i','numeric_kind':'int','bit_width':32,'endianness':'little','element_size_bytes':4},
]
for s in series_defs:
 d=samples_dir/s['series_id']
 if d.exists(): shutil.rmtree(d)
 d.mkdir(parents=True, exist_ok=True)
vals={s['series_id']:[] for s in series_defs}
row_count=0; kept=0; skipped=0
with zipfile.ZipFile(download_dir/'allCountries.zip') as zf:
    with zf.open('allCountries.txt') as fh:
        for raw in fh:
            row_count += 1
            try:
                parts=raw.decode('utf-8').rstrip('\n').split('\t')
                lat=float(parts[4]); lon=float(parts[5]); population=int(parts[14] or 0)
                elevation=int(parts[15]) if parts[15] else INT32_MIN
                dem=int(parts[16]) if parts[16] else INT32_MIN
            except Exception:
                skipped += 1
                continue
            vals['geonames_latitude_f32'].append(lat)
            vals['geonames_longitude_f32'].append(lon)
            vals['geonames_population_u64'].append(population)
            vals['geonames_elevation_i32'].append(elevation)
            vals['geonames_dem_i32'].append(dem)
            kept += 1
with (filter_dir/'stats.tsv').open('w', encoding='utf-8', newline='') as f:
    w=csv.writer(f, delimiter='\t'); w.writerow(['row_count','kept_count','skipped_count']); w.writerow([row_count, kept, skipped])
records=[]
for s in series_defs:
    out=samples_dir/s['series_id']/'allcountries.bin'
    if s.get('kind') == 'float32':
        with out.open('wb') as fh:
            for value in vals[s['series_id']]:
                fh.write(struct.pack('<f', value))
    else:
        arr=array.array(s['array_type'], vals[s['series_id']])
        if arr.itemsize > 1 and os.sys.byteorder != 'little': arr.byteswap()
        with out.open('wb') as fh: fh.write(arr.tobytes())
    records.append({'dataset_id':'geonames_allcountries','series_id':s['series_id'],'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':s['numeric_kind'],'bit_width':s['bit_width'],'endianness':s['endianness'],'element_size_bytes':s['element_size_bytes'],'sample_size_bytes':out.stat().st_size,'value_count':len(vals[s['series_id']])})
import json
with (index_dir/'samples.jsonl').open('w', encoding='utf-8') as fh:
    for row in records: fh.write(json.dumps(row, sort_keys=True)+'\n')
if kept < 1000000: raise SystemExit(f'kept too few rows: {kept}')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
