#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="met_biocollection_objects"
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
src=json.load((download_dir/"met_biocollection_objects.json").open(encoding="utf-8"))
values=[int(v) for v in src["objectIDs"] if v is not None]
out_dir=samples_dir/"met_object_id"
if out_dir.exists(): shutil.rmtree(out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
out=out_dir/f"met_object_id_u32_n{len(values):06d}.bin"
with out.open("wb") as fh: fh.write(struct.pack("<"+"I"*len(values), *values))
row={"dataset_id":"met_biocollection_objects","series_id":"met_object_id","sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":"uint","bit_width":32,"endianness":"little","element_size_bytes":4,"sample_size_bytes":out.stat().st_size,"value_count":len(values)}
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"met_biocollection_objects","rows_total":len(src["objectIDs"]),"rows_skipped":len(src["objectIDs"])-len(values)},indent=2,sort_keys=True)+"\n",encoding="utf-8")
with (index_dir/"samples.jsonl").open("w",encoding="utf-8") as fh: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
