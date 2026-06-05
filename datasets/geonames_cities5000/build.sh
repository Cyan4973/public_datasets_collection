#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="geonames_cities5000"
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
import json, os, shutil, struct, zipfile
from pathlib import Path
repo_root = Path(os.environ["REPO_ROOT"]); data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"]); filter_dir = Path(os.environ["FILTER_DIR"]); index_dir = Path(os.environ["INDEX_DIR"]); samples_dir = Path(os.environ["SAMPLES_DIR"])
raw = download_dir / "cities5000.zip"
if not raw.is_file(): raise RuntimeError("missing archive")
defs={"geonames_latitude":("float",64,"d"),"geonames_longitude":("float",64,"d"),"geonames_population":("uint",32,"I")}
for sid in defs:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
lats=[]; lons=[]; pops=[]; blank={"geonames_latitude":0,"geonames_longitude":0,"geonames_population":0}; total=0
with zipfile.ZipFile(raw) as zf:
    with zf.open("cities5000.txt") as fh:
        for line in fh:
            parts=line.decode("utf-8").rstrip("\n").split("\t")
            total += 1
            lat=parts[4].strip(); lon=parts[5].strip(); pop=parts[14].strip() if len(parts)>14 else ""
            if lat=="": blank["geonames_latitude"] += 1
            else: lats.append(float(lat))
            if lon=="": blank["geonames_longitude"] += 1
            else: lons.append(float(lon))
            if pop=="": blank["geonames_population"] += 1
            else: pops.append(int(pop))
rows=[]
for sid, values in [("geonames_latitude",lats),("geonames_longitude",lons),("geonames_population",pops)]:
    kind,bits,code=defs[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as f: f.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"geonames_cities5000","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
stats={"dataset_id":"geonames_cities5000","rows_total":total,"series":{sid:{"kept_rows":len(vals),"blank_rows_filtered":blank[sid]} for sid,vals in [("geonames_latitude",lats),("geonames_longitude",lons),("geonames_population",pops)]}}
(filter_dir/"ingest_stats.json").write_text(json.dumps(stats,indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
