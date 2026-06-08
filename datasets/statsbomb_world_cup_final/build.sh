#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="statsbomb_world_cup_final"
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
events=json.load((download_dir/"statsbomb_events_wc_final.json").open(encoding="utf-8"))
matches=json.load((download_dir/"statsbomb_matches_wc_final.json").open(encoding="utf-8"))
series={
 "statsbomb_event_index":[],"statsbomb_event_minute":[],"statsbomb_event_second":[],"statsbomb_event_duration":[],
 "statsbomb_event_location_x":[],"statsbomb_event_location_y":[],
 "statsbomb_match_home_score":[],"statsbomb_match_away_score":[],"statsbomb_match_week":[]
}
skipped={k:0 for k in series}
rows_total={"events":len(events),"matches":len(matches)}
for ev in events:
    for key, field, conv in [
        ("statsbomb_event_index","index",int),
        ("statsbomb_event_minute","minute",int),
        ("statsbomb_event_second","second",int),
        ("statsbomb_event_duration","duration",float),
    ]:
        try: series[key].append(conv(ev[field]))
        except Exception: skipped[key]+=1
    loc=ev.get("location")
    if isinstance(loc,list) and len(loc)>=2:
        series["statsbomb_event_location_x"].append(float(loc[0]))
        series["statsbomb_event_location_y"].append(float(loc[1]))
    else:
        skipped["statsbomb_event_location_x"] += 1
        skipped["statsbomb_event_location_y"] += 1
for match in matches:
    for key, field in [("statsbomb_match_home_score","home_score"),("statsbomb_match_away_score","away_score"),("statsbomb_match_week","match_week")]:
        try: series[key].append(int(match[field]))
        except Exception: skipped[key]+=1
meta={
 "statsbomb_event_index":("uint",32,"I"),"statsbomb_event_minute":("uint",16,"H"),
 "statsbomb_event_second":("uint",8,"B"),"statsbomb_event_duration":("float",32,"f"),
 "statsbomb_event_location_x":("float",32,"f"),"statsbomb_event_location_y":("float",32,"f"),
 "statsbomb_match_home_score":("uint",8,"B"),"statsbomb_match_away_score":("uint",8,"B"),
 "statsbomb_match_week":("uint",16,"H")
}
rows=[]
for sid,values in series.items():
    out_dir=samples_dir/sid
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kind,bits,code=meta[sid]
    out=out_dir/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh: fh.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"statsbomb_world_cup_final","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"statsbomb_world_cup_final","rows_total":rows_total,"rows_skipped":skipped},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
