#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="library_of_congress_items"
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
from datetime import datetime
from pathlib import Path
repo_root=Path(os.environ["REPO_ROOT"]); data_root=repo_root/os.environ["DATA_DIR"]
download_dir=Path(os.environ["DOWNLOAD_DIR"]); filter_dir=Path(os.environ["FILTER_DIR"]); index_dir=Path(os.environ["INDEX_DIR"]); samples_dir=Path(os.environ["SAMPLES_DIR"])
results=json.load(open(download_dir/"items.json",encoding='utf-8'))["results"]
vals={"loc_extract_timestamp":[],"loc_numeric_shelf_id":[],"loc_resource_files_sum":[],"loc_resource_segments_sum":[]}; skipped=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
def ts(s:str)->int:
    return calendar.timegm(datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").utctimetuple())
for row in results:
    try:
        resources=row.get("resources",[]) or []
        vals["loc_extract_timestamp"].append(ts(row["extract_timestamp"]))
        vals["loc_numeric_shelf_id"].append(int(row["numeric_shelf_id"]))
        vals["loc_resource_files_sum"].append(sum(int(r.get("files",0)) for r in resources))
        vals["loc_resource_segments_sum"].append(sum(int(r.get("segments",0)) for r in resources))
    except Exception:
        skipped += 1
meta={"loc_extract_timestamp":("uint",32,"I"),"loc_numeric_shelf_id":("uint",64,"Q"),"loc_resource_files_sum":("uint",16,"H"),"loc_resource_segments_sum":("uint",16,"H")}
rows=[]
for sid,values in vals.items():
    kind,bits,code=meta[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh: fh.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"library_of_congress_items","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"library_of_congress_items","rows_total":len(results),"rows_skipped":skipped},indent=2,sort_keys=True)+"\n",encoding='utf-8')
with (index_dir/"samples.jsonl").open("w",encoding='utf-8') as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"

