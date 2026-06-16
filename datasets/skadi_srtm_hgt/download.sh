#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="skadi_srtm_hgt"
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
TARGET="$DOWNLOAD_DIR/N37W122.hgt.gz"
URL="https://s3.amazonaws.com/elevation-tiles-prod/skadi/N37/N37W122.hgt.gz"
if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  tmp="$TARGET.tmp"
  rm -f "$tmp"
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$URL"
  mv "$tmp" "$TARGET"
fi

export TARGET
python3 - <<'PY'
from __future__ import annotations

import gzip
import os
from pathlib import Path

target = Path(os.environ["TARGET"])
if not target.is_file() or target.stat().st_size == 0:
    raise SystemExit(f"missing downloaded HGT gzip: {target}")
raw = gzip.decompress(target.read_bytes())
expected = 3601 * 3601 * 2
if len(raw) != expected:
    raise SystemExit(f"unexpected decoded HGT size: {len(raw)} != {expected}")
print(f"semantic_validation=ok source_bytes={target.stat().st_size} decoded_bytes={len(raw)}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
