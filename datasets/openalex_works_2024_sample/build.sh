#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="openalex_works_2024_sample"
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
results = json.load(open(download_dir / "openalex_works_2024_sample.json", encoding="utf-8"))["results"]
defs={"openalex_cited_by_count":("I","cited_by_count"),"openalex_publication_year":("H","publication_year"),"openalex_referenced_works_count":("I","referenced_works_count")}
vals={sid:[] for sid in defs}; skipped=0
for sid in defs:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for item in results:
    try:
        vals["openalex_cited_by_count"].append(int(item["cited_by_count"]))
        vals["openalex_publication_year"].append(int(item["publication_year"]))
        vals["openalex_referenced_works_count"].append(int(item["referenced_works_count"]))
    except Exception:
        skipped += 1
rows=[]; meta={"openalex_cited_by_count":("uint",32,"I"),"openalex_publication_year":("uint",16,"H"),"openalex_referenced_works_count":("uint",32,"I")}
for sid,values in vals.items():
    kind,bits,code=meta[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as f: f.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"openalex_works_2024_sample","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
stats={"dataset_id":"openalex_works_2024_sample","rows_total":len(results),"rows_skipped":skipped,"series":{sid:{"kept_rows":len(vals[sid])} for sid in vals}}
(filter_dir/"ingest_stats.json").write_text(json.dumps(stats,indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"

