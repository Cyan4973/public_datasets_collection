#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="ucsc_hg38_chromosomes_u8"
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
curl -fL --retry 3 --retry-delay 5 -o "$DOWNLOAD_DIR/hg38.fa.gz" \
  "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.fa.gz"

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import gzip
import os
from pathlib import Path

archive = Path(os.environ["DOWNLOAD_DIR"]) / "hg38.fa.gz"
expected = {f"chr{i}" for i in range(1, 23)} | {"chrX", "chrY", "chrM"}
seen: set[str] = set()
with gzip.open(archive, "rb") as fh:
    for raw in fh:
        if raw.startswith(b">"):
            name = raw[1:].split(None, 1)[0].decode("ascii", "strict")
            if name in expected:
                seen.add(name)
missing = sorted(expected - seen)
if missing:
    raise SystemExit(f"missing primary chromosomes: {missing}")
print(f"semantic_validation=ok primary_chromosomes={len(seen)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
