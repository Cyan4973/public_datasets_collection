#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="football_data_epl_results"
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
repo_root=Path(os.environ["REPO_ROOT"]); data_root=repo_root/os.environ["DATA_DIR"]
download_dir=Path(os.environ["DOWNLOAD_DIR"]); filter_dir=Path(os.environ["FILTER_DIR"]); index_dir=Path(os.environ["INDEX_DIR"]); samples_dir=Path(os.environ["SAMPLES_DIR"])
with (download_dir/"football_data_epl_results.csv").open(newline='', encoding='utf-8', errors='replace') as fh:
    rows_src=list(csv.DictReader(fh))
series={k:[] for k in ["football_fthg","football_ftag","football_hs","football_as","football_hst","football_ast","football_hc","football_ac","football_hy","football_ay","football_hr","football_ar","football_avg_h","football_avg_d","football_avg_a"]}
skipped={k:0 for k in series}
mapping={
 "football_fthg":("FTHG",int),"football_ftag":("FTAG",int),"football_hs":("HS",int),"football_as":("AS",int),
 "football_hst":("HST",int),"football_ast":("AST",int),"football_hc":("HC",int),"football_ac":("AC",int),
 "football_hy":("HY",int),"football_ay":("AY",int),"football_hr":("HR",int),"football_ar":("AR",int),
 "football_avg_h":("AvgH",float),"football_avg_d":("AvgD",float),"football_avg_a":("AvgA",float),
}
for row in rows_src:
    for sid,(field,conv) in mapping.items():
        try: series[sid].append(conv(row[field]))
        except Exception: skipped[sid]+=1
meta={
 "football_fthg":("uint",8,"B"),"football_ftag":("uint",8,"B"),"football_hs":("uint",16,"H"),"football_as":("uint",16,"H"),
 "football_hst":("uint",16,"H"),"football_ast":("uint",16,"H"),"football_hc":("uint",16,"H"),"football_ac":("uint",16,"H"),
 "football_hy":("uint",8,"B"),"football_ay":("uint",8,"B"),"football_hr":("uint",8,"B"),"football_ar":("uint",8,"B"),
 "football_avg_h":("float",32,"f"),"football_avg_d":("float",32,"f"),"football_avg_a":("float",32,"f")}
rows=[]
for sid,values in series.items():
    out_dir=samples_dir/sid
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kind,bits,code=meta[sid]
    out=out_dir/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh: fh.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"football_data_epl_results","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"football_data_epl_results","rows_total":len(rows_src),"rows_skipped":skipped},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
