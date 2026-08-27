#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_morphodunes_piv_f64"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/morphodunes.py" verify \
  --selection "$RECIPE_DIR/selection.tsv" \
  --files-dir "$DOWNLOAD_DIR/files" --record "$DOWNLOAD_DIR/zenodo_record_16414450.json" \
  --samples-dir "$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
