#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="chesscom_hikaru_2024_01"
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
games = json.load(open(download_dir / "chesscom_hikaru_2024_01.json", encoding="utf-8"))["games"]
vals={"chesscom_white_rating":[],"chesscom_black_rating":[],"chesscom_end_time":[]}; skipped=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for game in games:
    try:
        vals["chesscom_white_rating"].append(int(game["white"]["rating"]))
        vals["chesscom_black_rating"].append(int(game["black"]["rating"]))
        vals["chesscom_end_time"].append(int(game["end_time"]))
    except Exception:
        skipped += 1
rows=[]; meta={"chesscom_white_rating":("uint",16,"H"),"chesscom_black_rating":("uint",16,"H"),"chesscom_end_time":("uint",32,"I")}
for sid,values in vals.items():
    kind,bits,code=meta[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as f: f.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"chesscom_hikaru_2024_01","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
stats={"dataset_id":"chesscom_hikaru_2024_01","rows_total":len(games),"rows_skipped":skipped,"series":{sid:{"kept_rows":len(vals[sid])} for sid in vals}}
(filter_dir/"ingest_stats.json").write_text(json.dumps(stats,indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"

