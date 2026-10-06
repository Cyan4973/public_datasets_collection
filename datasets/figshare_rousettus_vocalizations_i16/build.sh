#!/usr/bin/env bash
# Decode the 400 downloaded member spans (local files only): ZIP local header
# -> raw LZMA1 (method 14) -> CRC32 against the central directory -> RIFF
# walk -> PCM data chunk, and emit one little-endian int16 sample per
# recording plus the sample index.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="figshare_rousettus_vocalizations_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/rousettus.py" build \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --data-root "$DATA_ROOT" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
