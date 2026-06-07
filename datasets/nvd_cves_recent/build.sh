#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nvd_cves_recent"
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
import calendar, json, os, shutil, struct
from datetime import datetime
from pathlib import Path
repo_root=Path(os.environ["REPO_ROOT"]); data_root=repo_root/os.environ["DATA_DIR"]
download_dir=Path(os.environ["DOWNLOAD_DIR"]); filter_dir=Path(os.environ["FILTER_DIR"]); index_dir=Path(os.environ["INDEX_DIR"]); samples_dir=Path(os.environ["SAMPLES_DIR"])
vulns=json.load(open(download_dir/"cves_recent.json",encoding='utf-8'))["vulnerabilities"]
vals={"nvd_published_at":[],"nvd_last_modified_at":[],"nvd_reference_count":[],"nvd_weakness_count":[],"nvd_description_count":[]}
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
def ts(s:str)->int:
    return calendar.timegm(datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").utctimetuple())
skipped=0
for wrap in vulns:
    try:
        cve=wrap["cve"]
        vals["nvd_published_at"].append(ts(cve["published"]))
        vals["nvd_last_modified_at"].append(ts(cve["lastModified"]))
        vals["nvd_reference_count"].append(len(cve.get("references",[])))
        vals["nvd_weakness_count"].append(len(cve.get("weaknesses",[])))
        vals["nvd_description_count"].append(len(cve.get("descriptions",[])))
    except Exception:
        skipped += 1
meta={"nvd_published_at":("uint",32,"I"),"nvd_last_modified_at":("uint",32,"I"),"nvd_reference_count":("uint",16,"H"),"nvd_weakness_count":("uint",16,"H"),"nvd_description_count":("uint",16,"H")}
rows=[]
for sid,values in vals.items():
    kind,bits,code=meta[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh: fh.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"nvd_cves_recent","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"nvd_cves_recent","rows_total":len(vulns),"rows_skipped":skipped},indent=2,sort_keys=True)+"\n",encoding='utf-8')
with (index_dir/"samples.jsonl").open("w",encoding='utf-8') as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"

