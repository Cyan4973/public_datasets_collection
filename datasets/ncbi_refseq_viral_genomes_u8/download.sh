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
URL="https://ftp.ncbi.nlm.nih.gov/refseq/release/viral/viral.1.1.genomic.fna.gz"
ARCHIVE="$DOWNLOAD_DIR/viral.1.1.genomic.fna.gz"
MAX_DOWNLOAD_BYTES="${REFSEQ_MAX_DOWNLOAD_BYTES:-1000000000}"

content_length="$(
  curl -fsSIL "$URL" \
    | awk 'BEGIN{IGNORECASE=1} /^content-length:/ {gsub("\r", "", $2); value=$2} END{print value}'
)"
if [ -n "$content_length" ] && [ "$content_length" -gt "$MAX_DOWNLOAD_BYTES" ]; then
  echo "remote archive exceeds REFSEQ_MAX_DOWNLOAD_BYTES: bytes=$content_length cap=$MAX_DOWNLOAD_BYTES"
  exit 1
fi
if [ -s "$ARCHIVE" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "archive cache_hit bytes=$(wc -c < "$ARCHIVE" | tr -d ' ')"
else
  curl -fL --retry 3 --retry-delay 5 -o "$ARCHIVE.tmp" "$URL"
  mv "$ARCHIVE.tmp" "$ARCHIVE"
fi
archive_bytes="$(wc -c < "$ARCHIVE" | tr -d ' ')"
if [ "$archive_bytes" -gt "$MAX_DOWNLOAD_BYTES" ]; then
  echo "downloaded archive exceeds REFSEQ_MAX_DOWNLOAD_BYTES: bytes=$archive_bytes cap=$MAX_DOWNLOAD_BYTES"
  exit 1
fi

export DOWNLOAD_DIR
export REFSEQ_MIN_RECORDS="${REFSEQ_MIN_RECORDS:-1000}"
export REFSEQ_MIN_SEQUENCE_BYTES="${REFSEQ_MIN_SEQUENCE_BYTES:-10000000}"
python3 - <<'PY'
from __future__ import annotations

import gzip
import os
from pathlib import Path

min_records = int(os.environ["REFSEQ_MIN_RECORDS"])
min_sequence_bytes = int(os.environ["REFSEQ_MIN_SEQUENCE_BYTES"])
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
if records < min_records:
    raise SystemExit(f"too few FASTA records: {records} < {min_records}")
if sequence_bytes < min_sequence_bytes:
    raise SystemExit(f"too little FASTA sequence payload: {sequence_bytes} < {min_sequence_bytes}")
print(f"semantic_validation=ok records={records} sequence_bytes={sequence_bytes}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
