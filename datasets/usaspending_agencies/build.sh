#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usaspending_agencies"
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
import json, os, shutil, struct
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
obj=json.load(open(download_dir/"usaspending_agencies.json",encoding='utf-8'))

items=obj["results"]
meta={"usaspending_agency_id": ["uint", 32, "I"], "usaspending_active_fq": ["uint", 8, "B"], "usaspending_active_fy": ["uint", 16, "H"], "usaspending_budget_authority_amount": ["float", 64, "d"], "usaspending_current_total_budget_authority_amount": ["float", 64, "d"], "usaspending_obligated_amount": ["float", 64, "d"], "usaspending_outlay_amount": ["float", 64, "d"], "usaspending_percentage_of_total_budget_authority": ["float", 64, "d"]}
vals={sid:[] for sid in meta}
skipped=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for row in items:
    try:
        vals["usaspending_agency_id"].append(int(row["agency_id"]))
        vals["usaspending_active_fq"].append(int(row["active_fq"]))
        vals["usaspending_active_fy"].append(int(row["active_fy"]))
        vals["usaspending_budget_authority_amount"].append(float(row["budget_authority_amount"]))
        vals["usaspending_current_total_budget_authority_amount"].append(float(row["current_total_budget_authority_amount"]))
        vals["usaspending_obligated_amount"].append(float(row["obligated_amount"]))
        vals["usaspending_outlay_amount"].append(float(row["outlay_amount"]))
        vals["usaspending_percentage_of_total_budget_authority"].append(float(row["percentage_of_total_budget_authority"]))
    except Exception:
        skipped += 1
rows=[]
for sid,(kind,bits,code) in meta.items():
    values=vals[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open('wb') as fh:
        fh.write(struct.pack('<' + code*len(values), *values))
    rows.append({"dataset_id":"usaspending_agencies","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/'ingest_stats.json').write_text(json.dumps({"dataset_id":"usaspending_agencies","rows_total":len(items),"rows_skipped":skipped},indent=2,sort_keys=True)+'\n',encoding='utf-8')
with (index_dir/'samples.jsonl').open('w',encoding='utf-8') as fh:
    for row in rows:
        fh.write(json.dumps(row,sort_keys=True)+'\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
