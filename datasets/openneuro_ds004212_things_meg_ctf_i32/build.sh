#!/usr/bin/env bash
# Build canonical little-endian int32 samples from the locally downloaded
# THINGS-MEG gradiometer channel blocks. Uses only local files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="openneuro_ds004212_things_meg_ctf_i32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/ctf_meg.py"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 "$TOOL" selftest
python3 "$TOOL" check-description --path "$DOWNLOAD_DIR/dataset_description.json"
python3 "$TOOL" audit --selection "$RECIPE_DIR/selection.tsv" --streams "$RECIPE_DIR/streams.tsv" \
  --download-dir "$DOWNLOAD_DIR" --require-pinned
python3 "$TOOL" build --selection "$RECIPE_DIR/selection.tsv" --streams "$RECIPE_DIR/streams.tsv" \
  --download-dir "$DOWNLOAD_DIR" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_ROOT"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
