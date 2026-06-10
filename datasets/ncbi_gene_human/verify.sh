#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=ncbi_gene_human
INDEX_PATH="$DATA_DIR/index/$DATASET_ID/samples.jsonl"
FILTERED_PATH="$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/verify.$TS.log"
LATEST_LOG="$LOG_DIR/verify.latest.log"
exec > >(tee "$LOG_FILE") 2>&1

python3 - <<'PY' "$INDEX_PATH" "$FILTERED_PATH"
import json
import os
import sys

idx, stats = sys.argv[1:3]
rows = [json.loads(line) for line in open(idx, encoding="utf-8")]
st = json.load(open(stats, encoding="utf-8"))

assert len(rows) == 4
expected = {
    "ncbi_gene_info_gene_id_u32": st["rows_info_kept"],
    "ncbi_gene_info_modification_date_u32": st["rows_info_kept"],
    "ncbi_gene2pubmed_gene_id_u32": st["rows_gene2pubmed_kept"],
    "ncbi_gene2pubmed_pubmed_id_u32": st["rows_gene2pubmed_kept"],
}
for r in rows:
    assert os.path.exists(r["sample_path"])
    assert r["sample_size_bytes"] == os.path.getsize(r["sample_path"])
    assert r["value_count"] == expected[r["series_id"]]

print(f"verified_samples={len(rows)} rows_info={st['rows_info_kept']} rows_gene2pubmed={st['rows_gene2pubmed_kept']}")
print("verify done dataset=ncbi_gene_human")
PY

cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
