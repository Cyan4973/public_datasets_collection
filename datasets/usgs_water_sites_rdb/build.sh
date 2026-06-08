#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="usgs_water_sites_rdb"
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
text=(download_dir/"usgs_water_sites_rdb.txt").read_text(encoding='utf-8', errors='replace').splitlines()
header_idx=next(i for i,line in enumerate(text) if line.startswith('agency_cd\t'))
header=text[header_idx].split('\t')
data_rows=[line.split('\t') for line in text[header_idx+2:] if line and not line.startswith('#')]
idx={name:i for i,name in enumerate(header)}
series={k:[] for k in ["usgs_site_no","usgs_dec_lat","usgs_dec_long","usgs_altitude","usgs_alt_accuracy","usgs_huc_cd"]}
skipped={k:0 for k in series}
for row in data_rows:
    vals={
        "usgs_site_no": row[idx["site_no"]],
        "usgs_dec_lat": row[idx["dec_lat_va"]],
        "usgs_dec_long": row[idx["dec_long_va"]],
        "usgs_altitude": row[idx["alt_va"]],
        "usgs_alt_accuracy": row[idx["alt_acy_va"]],
        "usgs_huc_cd": row[idx["huc_cd"]],
    }
    for sid,val in vals.items():
        try:
            if sid in {"usgs_site_no"}:
                series[sid].append(int(val))
            elif sid in {"usgs_huc_cd"}:
                series[sid].append(int(val))
            elif sid == "usgs_alt_accuracy":
                series[sid].append(float(val))
            else:
                series[sid].append(float(val))
        except Exception:
            skipped[sid]+=1
meta={"usgs_site_no":("uint",64,"Q"),"usgs_dec_lat":("float",64,"d"),"usgs_dec_long":("float",64,"d"),"usgs_altitude":("float",64,"d"),"usgs_alt_accuracy":("float",32,"f"),"usgs_huc_cd":("uint",64,"Q")}
rows=[]
for sid,values in series.items():
    out_dir=samples_dir/sid
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kind,bits,code=meta[sid]
    out=out_dir/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh: fh.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"usgs_water_sites_rdb","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"usgs_water_sites_rdb","rows_total":len(data_rows),"rows_skipped":skipped},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
