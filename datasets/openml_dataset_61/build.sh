#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openml_dataset_61"
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
raw = download_dir / "dataset_61.arff"
if not raw.is_file(): raise RuntimeError("missing arff")
defs=["iris_sepallength","iris_sepalwidth","iris_petallength","iris_petalwidth"]
vals={k:[] for k in defs}
for sid in defs:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
in_data=False; total=0
for line in raw.read_text(encoding="utf-8").splitlines():
    s=line.strip()
    if not s or s.startswith("%"): continue
    if not in_data:
        if s.lower()=="@data": in_data=True
        continue
    parts=[p.strip() for p in s.split(",")]
    if len(parts) < 5: raise RuntimeError(f"bad row: {s}")
    total += 1
    for i,sid in enumerate(defs): vals[sid].append(float(parts[i]))
rows=[]
for sid in defs:
    out=samples_dir/sid/f"{sid}_f32_n{len(vals[sid]):06d}.bin"
    with out.open("wb") as f: f.write(struct.pack("<"+"f"*len(vals[sid]), *vals[sid]))
    rows.append({"dataset_id":"openml_dataset_61","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":"float","bit_width":32,"endianness":"little","element_size_bytes":4,"sample_size_bytes":out.stat().st_size,"value_count":len(vals[sid])})
stats={"dataset_id":"openml_dataset_61","rows_total":total,"series":{sid:{"kept_rows":len(vals[sid])} for sid in defs}}
(filter_dir/"ingest_stats.json").write_text(json.dumps(stats,indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"

