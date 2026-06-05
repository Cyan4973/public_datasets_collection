#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="jpl_cad_2024"
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
repo_root = Path(os.environ["REPO_ROOT"]); data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"]); filter_dir = Path(os.environ["FILTER_DIR"]); index_dir = Path(os.environ["INDEX_DIR"]); samples_dir = Path(os.environ["SAMPLES_DIR"])
obj = json.load(open(download_dir / "cad_2024.json", encoding="utf-8"))
fields = {name:i for i,name in enumerate(obj["fields"])}
defs={"jpl_cad_jd":"jd","jpl_cad_dist":"dist","jpl_cad_v_rel":"v_rel","jpl_cad_v_inf":"v_inf"}
vals={sid:[] for sid in defs}
for sid in defs:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for row in obj["data"]:
    for sid,field in defs.items(): vals[sid].append(float(row[fields[field]]))
rows=[]
for sid in defs:
    out=samples_dir/sid/f"{sid}_f64_n{len(vals[sid]):06d}.bin"
    with out.open("wb") as f: f.write(struct.pack("<"+"d"*len(vals[sid]), *vals[sid]))
    rows.append({"dataset_id":"jpl_cad_2024","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":"float","bit_width":64,"endianness":"little","element_size_bytes":8,"sample_size_bytes":out.stat().st_size,"value_count":len(vals[sid])})
stats={"dataset_id":"jpl_cad_2024","rows_total":len(obj["data"]),"series":{sid:{"kept_rows":len(vals[sid])} for sid in defs}}
(filter_dir/"ingest_stats.json").write_text(json.dumps(stats,indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"

