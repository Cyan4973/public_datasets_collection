#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ncbi_assembly_refseq_summary"
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
import csv, json, os, shutil, struct
from pathlib import Path
repo_root=Path(os.environ["REPO_ROOT"]); data_root=repo_root/os.environ["DATA_DIR"]
download_dir=Path(os.environ["DOWNLOAD_DIR"]); filter_dir=Path(os.environ["FILTER_DIR"]); index_dir=Path(os.environ["INDEX_DIR"]); samples_dir=Path(os.environ["SAMPLES_DIR"])
raw=download_dir/"assembly_summary_refseq.txt"
vals={"ncbi_assembly_taxid":[],"ncbi_assembly_genome_size":[],"ncbi_assembly_gc_percent":[],"ncbi_assembly_total_gene_count":[],"ncbi_assembly_protein_coding_gene_count":[]}; skipped=0; total=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
with raw.open(encoding='utf-8', newline='') as fh:
    for line in fh:
        if line.startswith('##'): continue
        if line.startswith('#'):
            header=line[1:].rstrip('\n').split('\t')
            reader=csv.DictReader(fh, fieldnames=header, delimiter='\t')
            break
    else:
        raise RuntimeError('missing header')
    for row in reader:
        total += 1
        try:
            vals["ncbi_assembly_taxid"].append(int(row["taxid"]))
            vals["ncbi_assembly_genome_size"].append(int(row["genome_size"]))
            vals["ncbi_assembly_gc_percent"].append(float(row["gc_percent"]))
            vals["ncbi_assembly_total_gene_count"].append(int(row["total_gene_count"]))
            vals["ncbi_assembly_protein_coding_gene_count"].append(int(row["protein_coding_gene_count"]))
        except Exception:
            skipped += 1
meta={"ncbi_assembly_taxid":("uint",32,"I"),"ncbi_assembly_genome_size":("uint",64,"Q"),"ncbi_assembly_gc_percent":("float",32,"f"),"ncbi_assembly_total_gene_count":("uint",32,"I"),"ncbi_assembly_protein_coding_gene_count":("uint",32,"I")}
rows=[]
for sid,values in vals.items():
    kind,bits,code=meta[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh: fh.write(struct.pack("<"+code*len(values), *values))
    rows.append({"dataset_id":"ncbi_assembly_refseq_summary","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
(filter_dir/"ingest_stats.json").write_text(json.dumps({"dataset_id":"ncbi_assembly_refseq_summary","rows_total":total,"rows_skipped":skipped},indent=2,sort_keys=True)+"\n",encoding='utf-8')
with (index_dir/"samples.jsonl").open("w",encoding='utf-8') as fh:
    for row in rows: fh.write(json.dumps(row,sort_keys=True)+"\n")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"

