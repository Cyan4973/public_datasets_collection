#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="gharchive_hourly_events_20240101_00"
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
import calendar, gzip, json, os, shutil, struct
from datetime import datetime
from pathlib import Path
repo_root=Path(os.environ["REPO_ROOT"]); data_root=repo_root/os.environ["DATA_DIR"]
download_dir=Path(os.environ["DOWNLOAD_DIR"]); filter_dir=Path(os.environ["FILTER_DIR"]); index_dir=Path(os.environ["INDEX_DIR"]); samples_dir=Path(os.environ["SAMPLES_DIR"])
vals={"gharchive_event_id":[],"gharchive_actor_id":[],"gharchive_repo_id":[],"gharchive_created_at":[]}
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
def ts(s:str)->int:
    return calendar.timegm(datetime.strptime(s,"%Y-%m-%dT%H:%M:%SZ").utctimetuple())
rows_total=0; skipped=0
with gzip.open(download_dir/"2024-01-01-0.json.gz",'rt',encoding='utf-8') as f:
    for line in f:
        rows_total += 1
        try:
            obj=json.loads(line)
            vals["gharchive_event_id"].append(int(obj["id"]))
            vals["gharchive_actor_id"].append(int(obj["actor"]["id"]))
            vals["gharchive_repo_id"].append(int(obj["repo"]["id"]))
            vals["gharchive_created_at"].append(ts(obj["created_at"]))
        except Exception:
            skipped += 1
meta={"gharchive_event_id":("uint",64,"Q"),"gharchive_actor_id":("uint",64,"Q"),"gharchive_repo_id":("uint",64,"Q"),"gharchive_created_at":("uint",32,"I")}
rows=[]
for sid,values in vals.items():
    kind,bits,code=meta[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh: fh.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"gharchive_hourly_events_20240101_00","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
stats={"dataset_id":"gharchive_hourly_events_20240101_00","rows_total":rows_total,"rows_skipped":skipped}
(filter_dir/"ingest_stats.json").write_text(json.dumps(stats,indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
