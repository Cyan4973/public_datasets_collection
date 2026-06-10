#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=ncbi_gene_human
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
FILTERED_DIR="$DATA_DIR/filtered/$DATASET_ID"
SAMPLES_DIR="$DATA_DIR/samples/$DATASET_ID"
INDEX_DIR="$DATA_DIR/index/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR" "$LOG_DIR"

TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/build.$TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE") 2>&1

python3 - <<'PY' "$DOWNLOAD_DIR/gene_info_human.tsv.gz" "$DOWNLOAD_DIR/gene2pubmed_human.tsv.gz" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import csv
import gzip
import json
import os
import struct
import sys

gene_info_path, gene2pubmed_path, filtered_dir, samples_dir, index_dir = sys.argv[1:6]

series = {
    "ncbi_gene_info_gene_id_u32": ("I", [], "uint", 32),
    "ncbi_gene_info_modification_date_u32": ("I", [], "uint", 32),
    "ncbi_gene2pubmed_gene_id_u32": ("I", [], "uint", 32),
    "ncbi_gene2pubmed_pubmed_id_u32": ("I", [], "uint", 32),
}

rows_info_total = 0
rows_info_kept = 0
with gzip.open(gene_info_path, "rt", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        rows_info_total += 1
        try:
            gene_id = int(row["GeneID"])
            mod_date = int(row["Modification_date"])
        except Exception:
            continue
        series["ncbi_gene_info_gene_id_u32"][1].append(gene_id)
        series["ncbi_gene_info_modification_date_u32"][1].append(mod_date)
        rows_info_kept += 1

rows_gene2pubmed_total = 0
rows_gene2pubmed_kept = 0
with gzip.open(gene2pubmed_path, "rt", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        rows_gene2pubmed_total += 1
        try:
            gene_id = int(row["GeneID"])
            pubmed_id = int(row["PubMed_ID"])
        except Exception:
            continue
        series["ncbi_gene2pubmed_gene_id_u32"][1].append(gene_id)
        series["ncbi_gene2pubmed_pubmed_id_u32"][1].append(pubmed_id)
        rows_gene2pubmed_kept += 1

index_path = os.path.join(index_dir, "samples.jsonl")
with open(index_path, "w", encoding="utf-8") as idx:
    for sid, (fmt, vals, nk, bw) in series.items():
        sdir = os.path.join(samples_dir, sid)
        os.makedirs(sdir, exist_ok=True)
        out = os.path.join(sdir, "human.bin")
        with open(out, "wb") as f:
            for v in vals:
                f.write(struct.pack("<" + fmt, v))
        idx.write(json.dumps({
            "dataset_id": "ncbi_gene_human",
            "series_id": sid,
            "sample_path": out,
            "numeric_kind": nk,
            "bit_width": bw,
            "endianness": "little",
            "element_size_bytes": bw // 8,
            "sample_size_bytes": os.path.getsize(out),
            "value_count": len(vals),
        }) + "\n")

with open(os.path.join(filtered_dir, "ingest_stats.json"), "w", encoding="utf-8") as f:
    json.dump({
        "rows_info_total": rows_info_total,
        "rows_info_kept": rows_info_kept,
        "rows_info_skipped": rows_info_total - rows_info_kept,
        "rows_gene2pubmed_total": rows_gene2pubmed_total,
        "rows_gene2pubmed_kept": rows_gene2pubmed_kept,
        "rows_gene2pubmed_skipped": rows_gene2pubmed_total - rows_gene2pubmed_kept,
        "sample_rows": len(series),
    }, f)

print("build done dataset=ncbi_gene_human")
PY

cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
