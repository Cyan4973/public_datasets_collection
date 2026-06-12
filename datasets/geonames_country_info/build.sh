#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="geonames_country_info"
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
meta={
  "geonames_country_iso_numeric_u16":("uint",16,"H"),
  "geonames_country_area_sqkm_f64":("float",64,"d"),
  "geonames_country_population_i64":("int",64,"q"),
  "geonames_country_phone_length_u8":("uint",8,"B"),
  "geonames_country_language_count_u8":("uint",8,"B"),
  "geonames_country_geonameid_u32":("uint",32,"I"),
  "geonames_country_neighbour_count_u8":("uint",8,"B"),
}
vals={sid:[] for sid in meta}; rows_total=0; rows_kept=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for line in (download_dir/"geonames_country_info.txt").open(encoding="utf-8"):
    if line.startswith("#") or not line.strip():
        continue
    rows_total += 1
    parts=line.rstrip("\n").split("\t")
    try:
        vals["geonames_country_iso_numeric_u16"].append(int(parts[2]))
        vals["geonames_country_area_sqkm_f64"].append(float(parts[6]))
        vals["geonames_country_population_i64"].append(int(parts[7]))
        vals["geonames_country_phone_length_u8"].append(len(parts[12]))
        vals["geonames_country_language_count_u8"].append(len([x for x in parts[15].split(",") if x]))
        vals["geonames_country_geonameid_u32"].append(int(parts[16]))
        vals["geonames_country_neighbour_count_u8"].append(len([x for x in parts[17].split(",") if x]))
        rows_kept += 1
    except Exception:
        continue
index_rows=[]
for sid,(kind,bits,code) in meta.items():
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(vals[sid]):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<"+code*len(vals[sid]), *vals[sid]))
    index_rows.append({"dataset_id":"geonames_country_info","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(vals[sid])})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"geonames_country_info","rows_total":rows_total,"rows_kept":rows_kept,"rows_skipped":rows_total-rows_kept},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in index_rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
