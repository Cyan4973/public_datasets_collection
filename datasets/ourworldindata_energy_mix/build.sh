#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ourworldindata_energy_mix"
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
import csv, json, os, shutil, struct
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
path=download_dir/'ourworldindata_energy_mix.csv'
meta={
 'owid_energy_mix_year_u16':('uint',16,'H'),
 'owid_energy_mix_nuclear_f32':('float',32,'f'),
 'owid_energy_mix_renewables_f32':('float',32,'f'),
 'owid_energy_mix_fossil_fuels_f32':('float',32,'f'),
 'owid_energy_mix_entity_length_u16':('uint',16,'H'),
 'owid_energy_mix_code_length_u8':('uint',8,'B'),
}
vals={sid:[] for sid in meta}
for sid in vals:
 d=samples_dir/sid
 if d.exists(): shutil.rmtree(d)
 d.mkdir(parents=True, exist_ok=True)
rows_total=0; rows_skipped=0
with path.open('r', encoding='utf-8', newline='') as f:
 r=csv.DictReader(f)
 for row in r:
  rows_total += 1
  try:
   nuclear=(row.get('Nuclear') or '').strip()
   renew=(row.get('Renewables') or '').strip()
   fossil=(row.get('Fossil fuels') or '').strip()
   if nuclear == '' and renew == '' and fossil == '':
    rows_skipped += 1
    continue
   vals['owid_energy_mix_year_u16'].append(int(row['Year']))
   vals['owid_energy_mix_nuclear_f32'].append(float(nuclear or 0))
   vals['owid_energy_mix_renewables_f32'].append(float(renew or 0))
   vals['owid_energy_mix_fossil_fuels_f32'].append(float(fossil or 0))
   vals['owid_energy_mix_entity_length_u16'].append(len(row.get('Entity','')))
   vals['owid_energy_mix_code_length_u8'].append(len((row.get('Code') or '').strip()))
  except Exception:
   rows_skipped += 1
rows=[]
for sid,(kind,bits,code) in meta.items():
 values=vals[sid]
 out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
 with out.open('wb') as fh: fh.write(struct.pack('<'+code*len(values), *values))
 rows.append({'dataset_id':'ourworldindata_energy_mix','series_id':sid,'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':kind,'bit_width':bits,'endianness':'little','element_size_bytes':bits//8,'sample_size_bytes':out.stat().st_size,'value_count':len(values)})
(filter_dir/'ingest_stats.json').write_text(json.dumps({'dataset_id':'ourworldindata_energy_mix','rows_total':rows_total,'rows_skipped':rows_skipped}, indent=2, sort_keys=True)+'\n', encoding='utf-8')
with (index_dir/'samples.jsonl').open('w', encoding='utf-8') as fh:
 for row in rows: fh.write(json.dumps(row, sort_keys=True)+'\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
