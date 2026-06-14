#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ncbi_refseq_viral_genomes_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
curl -fL --retry 3 --retry-delay 5 -o "$DOWNLOAD_DIR/viral.1.1.genomic.fna.gz" \
  "https://ftp.ncbi.nlm.nih.gov/refseq/release/viral/viral.1.1.genomic.fna.gz"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import gzip
import os
from pathlib import Path

archive = Path(os.environ["DOWNLOAD_DIR"]) / "viral.1.1.genomic.fna.gz"
records = 0
sequence_bytes = 0
with gzip.open(archive, "rb") as fh:
    first = fh.readline()
    if not first.startswith(b">"):
        raise SystemExit("expected FASTA header as first line")
    records = 1
    for raw in fh:
        if raw.startswith(b">"):
            records += 1
        else:
            sequence_bytes += len(raw.strip())
if records < 100:
    raise SystemExit(f"too few FASTA records: {records}")
if sequence_bytes < 100 * 1024:
    raise SystemExit(f"too little FASTA sequence payload: {sequence_bytes}")
print(f"semantic_validation=ok records={records} sequence_bytes={sequence_bytes}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
