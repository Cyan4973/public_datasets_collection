#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ncbi_taxdump"
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
import json, os, shutil, struct, tarfile
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
meta={'ncbi_nodes_tax_id_u32':('uint',32,'I'),'ncbi_nodes_parent_tax_id_u32':('uint',32,'I'),'ncbi_nodes_rank_length_u16':('uint',16,'H'),'ncbi_names_tax_id_u32':('uint',32,'I'),'ncbi_names_name_length_u16':('uint',16,'H')}
vals={k:[] for k in meta}; skipped=0; rows_total=0
for sid in vals:
 d=samples_dir/sid
 if d.exists(): shutil.rmtree(d)
 d.mkdir(parents=True, exist_ok=True)
with tarfile.open(download_dir/'ncbi_taxdump.tar.gz','r:gz') as tf:
 f=tf.extractfile('nodes.dmp')
 for raw in f:
  rows_total += 1
  try:
   parts=[p.strip() for p in raw.decode('utf-8','replace').split('|')]
   vals['ncbi_nodes_tax_id_u32'].append(int(parts[0]))
   vals['ncbi_nodes_parent_tax_id_u32'].append(int(parts[1]))
   vals['ncbi_nodes_rank_length_u16'].append(len(parts[2]))
  except Exception:
   skipped += 1
 f=tf.extractfile('names.dmp')
 for raw in f:
  rows_total += 1
  try:
   parts=[p.strip() for p in raw.decode('utf-8','replace').split('|')]
   vals['ncbi_names_tax_id_u32'].append(int(parts[0]))
   vals['ncbi_names_name_length_u16'].append(len(parts[1]))
  except Exception:
   skipped += 1
rows=[]
for sid,(kind,bits,code) in meta.items():
 values=vals[sid]
 out=samples_dir/sid/f'{sid}_{kind}{bits}_n{len(values):08d}.bin'
 with out.open('wb') as fh: fh.write(struct.pack('<'+code*len(values), *values))
 rows.append({'dataset_id':'ncbi_taxdump','series_id':sid,'sample_path':out.relative_to(data_root).as_posix(),'numeric_kind':kind,'bit_width':bits,'endianness':'little','element_size_bytes':bits//8,'sample_size_bytes':out.stat().st_size,'value_count':len(values)})
(filter_dir/'ingest_stats.json').write_text(json.dumps({'dataset_id':'ncbi_taxdump','rows_total':rows_total,'rows_skipped':skipped},indent=2,sort_keys=True)+'\n',encoding='utf-8')
with (index_dir/'samples.jsonl').open('w',encoding='utf-8') as fh:
 for row in rows: fh.write(json.dumps(row,sort_keys=True)+'\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
