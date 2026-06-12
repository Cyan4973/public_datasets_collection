#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_coops_stations"
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
import json, os, shutil, struct
from pathlib import Path
repo_root=Path(os.environ["REPO_ROOT"]); data_root=repo_root/os.environ["DATA_DIR"]
download_dir=Path(os.environ["DOWNLOAD_DIR"]); filter_dir=Path(os.environ["FILTER_DIR"]); index_dir=Path(os.environ["INDEX_DIR"]); samples_dir=Path(os.environ["SAMPLES_DIR"])
rows=json.load(open(download_dir/"noaa_coops_stations.json",encoding="utf-8"))["stations"]
meta={
  "noaa_coops_station_id_u32":("uint",32,"I"),
  "noaa_coops_station_lat_f64":("float",64,"d"),
  "noaa_coops_station_lng_f64":("float",64,"d"),
  "noaa_coops_station_timezonecorr_i16":("int",16,"h"),
  "noaa_coops_station_tidal_u8":("uint",8,"B"),
  "noaa_coops_station_greatlakes_u8":("uint",8,"B"),
  "noaa_coops_station_affiliation_count_u8":("uint",8,"B"),
}
vals={sid:[] for sid in meta}; rows_total=0; rows_kept=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for row in rows:
    rows_total += 1
    try:
        vals["noaa_coops_station_id_u32"].append(int(row["id"]))
        vals["noaa_coops_station_lat_f64"].append(float(row["lat"]))
        vals["noaa_coops_station_lng_f64"].append(float(row["lng"]))
        vals["noaa_coops_station_timezonecorr_i16"].append(int(row.get("timezonecorr") or 0))
        vals["noaa_coops_station_tidal_u8"].append(1 if row.get("tidal") else 0)
        vals["noaa_coops_station_greatlakes_u8"].append(1 if row.get("greatlakes") else 0)
        vals["noaa_coops_station_affiliation_count_u8"].append(len(row.get("affiliations") or []))
        rows_kept += 1
    except Exception:
        continue
index_rows=[]
for sid,(kind,bits,code) in meta.items():
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(vals[sid]):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<"+code*len(vals[sid]), *vals[sid]))
    index_rows.append({"dataset_id":"noaa_coops_stations","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(vals[sid])})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"noaa_coops_stations","rows_total":rows_total,"rows_kept":rows_kept,"rows_skipped":rows_total-rows_kept},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in index_rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
