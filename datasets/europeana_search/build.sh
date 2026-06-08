#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="europeana_search"
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
repo_root=Path(os.environ["REPO_ROOT"]); data_root=repo_root/os.environ["DATA_DIR"]
download_dir=Path(os.environ["DOWNLOAD_DIR"]); filter_dir=Path(os.environ["FILTER_DIR"]); index_dir=Path(os.environ["INDEX_DIR"]); samples_dir=Path(os.environ["SAMPLES_DIR"])
src=json.load((download_dir/"europeana_search.json").open(encoding="utf-8"))
series={"europeana_completeness":[],"europeana_index":[],"europeana_score":[],"europeana_timestamp_created_epoch":[],"europeana_timestamp_update_epoch":[]}
skipped={k:0 for k in series}
for item in src["items"]:
    vals={
        "europeana_completeness": item.get("completeness"),
        "europeana_index": item.get("index"),
        "europeana_score": item.get("score"),
        "europeana_timestamp_created_epoch": item.get("timestamp_created_epoch"),
        "europeana_timestamp_update_epoch": item.get("timestamp_update_epoch"),
    }
    for sid,val in vals.items():
        try:
            if sid == "europeana_score": series[sid].append(float(val))
            else: series[sid].append(int(val))
        except Exception: skipped[sid]+=1
meta={"europeana_completeness":("uint",8,"B"),"europeana_index":("uint",16,"H"),"europeana_score":("float",32,"f"),"europeana_timestamp_created_epoch":("uint",64,"Q"),"europeana_timestamp_update_epoch":("uint",64,"Q")}
rows=[]
for sid,values in series.items():
    out_dir=samples_dir/sid
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kind,bits,code=meta[sid]
    out=out_dir/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh: fh.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"europeana_search","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"europeana_search","rows_total":len(src["items"]),"rows_skipped":skipped},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
