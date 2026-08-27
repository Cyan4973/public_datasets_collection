#!/usr/bin/env bash
# Build separate little-endian TCP sequence and acknowledgment trajectories.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_zeroswarm_tcp_sequence_u32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/tcp32.py" build \
  --selection "$RECIPE_DIR/selection.tsv" --profiles "$RECIPE_DIR/profiles.tsv" \
  --record "$DOWNLOAD_DIR/zenodo_record_15082260.json" \
  --download-dir "$DOWNLOAD_DIR" \
  --samples-dir "$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
