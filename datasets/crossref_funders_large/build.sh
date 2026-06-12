#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="crossref_funders_large"
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
rows=json.load(open(download_dir/"crossref_funders_large.json",encoding="utf-8"))["message"]["items"]
meta={
  "crossref_funder_numeric_id_u32":("uint",32,"I"),
  "crossref_funder_token_count_u8":("uint",8,"B"),
  "crossref_funder_alt_name_count_u8":("uint",8,"B"),
  "crossref_funder_name_length_u16":("uint",16,"H"),
  "crossref_funder_location_length_u16":("uint",16,"H"),
}
vals={sid:[] for sid in meta}; rows_total=0; rows_kept=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for row in rows:
    rows_total += 1
    try:
        vals["crossref_funder_numeric_id_u32"].append(int(row["id"]))
        vals["crossref_funder_token_count_u8"].append(min(len(row.get("tokens") or []), 255))
        vals["crossref_funder_alt_name_count_u8"].append(min(len(row.get("alt-names") or []), 255))
        vals["crossref_funder_name_length_u16"].append(len(row.get("name") or ""))
        vals["crossref_funder_location_length_u16"].append(len(row.get("location") or ""))
        rows_kept += 1
    except Exception:
        continue
index_rows=[]
for sid,(kind,bits,code) in meta.items():
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(vals[sid]):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<"+code*len(vals[sid]), *vals[sid]))
    index_rows.append({"dataset_id":"crossref_funders_large","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(vals[sid])})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"crossref_funders_large","rows_total":rows_total,"rows_kept":rows_kept,"rows_skipped":rows_total-rows_kept},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in index_rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
