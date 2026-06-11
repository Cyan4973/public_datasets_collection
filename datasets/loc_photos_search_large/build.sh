#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="loc_photos_search_large"
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
import calendar, json, os, shutil, struct
from datetime import datetime
from pathlib import Path
repo_root=Path(os.environ["REPO_ROOT"]); data_root=repo_root/os.environ["DATA_DIR"]
download_dir=Path(os.environ["DOWNLOAD_DIR"]); filter_dir=Path(os.environ["FILTER_DIR"]); index_dir=Path(os.environ["INDEX_DIR"]); samples_dir=Path(os.environ["SAMPLES_DIR"])
rows=json.load(open(download_dir/"loc_photos_search_large.json",encoding="utf-8"))["results"]
meta={
  "loc_photos_index_u16":("uint",16,"H"),
  "loc_photos_extract_timestamp_u32":("uint",32,"I"),
  "loc_photos_year_u16":("uint",16,"H"),
  "loc_photos_online_format_count_u16":("uint",16,"H"),
  "loc_photos_subject_count_u16":("uint",16,"H"),
  "loc_photos_partof_count_u16":("uint",16,"H"),
  "loc_photos_location_count_u16":("uint",16,"H"),
}
vals={sid:[] for sid in meta}
skipped=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for row in rows:
    try:
        vals["loc_photos_index_u16"].append(int(row["index"]))
        vals["loc_photos_extract_timestamp_u32"].append(calendar.timegm(datetime.strptime(row["extract_timestamp"][:19],"%Y-%m-%dT%H:%M:%S").utctimetuple()))
        vals["loc_photos_year_u16"].append(int((row.get("date") or "0")[:4]))
        vals["loc_photos_online_format_count_u16"].append(len(row.get("online_format") or []))
        vals["loc_photos_subject_count_u16"].append(len(row.get("subject") or []))
        vals["loc_photos_partof_count_u16"].append(len(row.get("partof") or []))
        vals["loc_photos_location_count_u16"].append(len(row.get("location") or []))
    except Exception:
        skipped += 1
index_rows=[]
for sid,(kind,bits,code) in meta.items():
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(vals[sid]):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<"+code*len(vals[sid]), *vals[sid]))
    index_rows.append({"dataset_id":"loc_photos_search_large","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(vals[sid])})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"loc_photos_search_large","rows_total":len(rows),"rows_skipped":skipped},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in index_rows:
        fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
