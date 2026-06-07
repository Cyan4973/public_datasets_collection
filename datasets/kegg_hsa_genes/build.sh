#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="kegg_hsa_genes"
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
import calendar, json, os, shutil, struct
from datetime import datetime, timezone
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
text=open(download_dir/"kegg_hsa_genes.txt",encoding='utf-8').read()

import re
items=[line for line in text.splitlines() if line.strip()]
meta={"kegg_gene_id": ["uint", 32, "I"], "kegg_is_cds": ["uint", 8, "B"], "kegg_coord_start": ["uint", 32, "I"], "kegg_coord_end": ["uint", 32, "I"]}
vals={sid:[] for sid in meta}
skipped=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for line in items:
    try:
        parts=line.split("	",1)
        head=parts[0]
        rest=parts[1]
        gene_id=int(head.split(":",1)[1])
        rest_parts=rest.split("	")
        feature_type=rest_parts[0]
        raw_coord=rest_parts[1]
        m=re.search(r'(?::|^)(\d+)\.\.(?:>|<)?(\d+)', raw_coord)
        coord_start=int(m.group(1)) if m else 0
        coord_end=int(m.group(2)) if m else 0
        vals["kegg_gene_id"].append(gene_id)
        vals["kegg_is_cds"].append(1 if feature_type == "CDS" else 0)
        vals["kegg_coord_start"].append(coord_start)
        vals["kegg_coord_end"].append(coord_end)
    except Exception:
        skipped += 1
rows=[]
for sid,(kind,bits,code) in meta.items():
    values=vals[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open('wb') as fh:
        fh.write(struct.pack('<' + code*len(values), *values))
    rows.append({"dataset_id":"kegg_hsa_genes","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/'ingest_stats.json').write_text(json.dumps({"dataset_id":"kegg_hsa_genes","rows_total":len(items),"rows_skipped":skipped},indent=2,sort_keys=True)+ '\n',encoding='utf-8')
with (index_dir/'samples.jsonl').open('w',encoding='utf-8') as fh:
    for row in rows:
        fh.write(json.dumps(row,sort_keys=True)+'\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
