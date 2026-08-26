#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_tess_lightcurves_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/tess.py" build \
  --selection "$RECIPE_DIR/selection.tsv" \
  --fits-dir "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/fits" \
  --mast-page "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/mast_tess_page.html" \
  --nasa-guidelines "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/nasa_media_usage_guidelines.html" \
  --samples-dir "$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
