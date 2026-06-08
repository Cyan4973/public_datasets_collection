#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="marine_regions_gazetteer"
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
src=json.load((download_dir/"marine_regions_gazetteer.json").open(encoding="utf-8"))
series={k:[] for k in ["marine_regions_mrgid","marine_regions_latitude","marine_regions_longitude","marine_regions_min_latitude","marine_regions_min_longitude","marine_regions_max_latitude","marine_regions_max_longitude","marine_regions_accepted"]}
skipped={k:0 for k in series}
for item in src:
    vals={
        "marine_regions_mrgid": item.get("MRGID"),
        "marine_regions_latitude": item.get("latitude"),
        "marine_regions_longitude": item.get("longitude"),
        "marine_regions_min_latitude": item.get("minLatitude"),
        "marine_regions_min_longitude": item.get("minLongitude"),
        "marine_regions_max_latitude": item.get("maxLatitude"),
        "marine_regions_max_longitude": item.get("maxLongitude"),
        "marine_regions_accepted": item.get("accepted"),
    }
    for sid,val in vals.items():
        try:
            if sid in {"marine_regions_mrgid","marine_regions_accepted"}: series[sid].append(int(val))
            else: series[sid].append(float(val))
        except Exception: skipped[sid]+=1
meta={
 "marine_regions_mrgid":("uint",32,"I"),"marine_regions_latitude":("float",64,"d"),"marine_regions_longitude":("float",64,"d"),
 "marine_regions_min_latitude":("float",64,"d"),"marine_regions_min_longitude":("float",64,"d"),"marine_regions_max_latitude":("float",64,"d"),
 "marine_regions_max_longitude":("float",64,"d"),"marine_regions_accepted":("uint",32,"I")
}
rows=[]
for sid,values in series.items():
    out_dir=samples_dir/sid
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kind,bits,code=meta[sid]
    out=out_dir/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh: fh.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"marine_regions_gazetteer","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"marine_regions_gazetteer","rows_total":len(src),"rows_skipped":skipped},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
