#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_sdo_aia_synoptic_i32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/aia_i32.py" verify \
  --selection "$RECIPE_DIR/selection.tsv" \
  --fits-dir "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/fits" \
  --funpack "$REPO_ROOT/$DATA_DIR/tools/$DATASET_ID/bin/funpack" \
  --sdo-copyright "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/sdo_copyright.html" \
  --nasa-guidelines "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/nasa_media_usage_guidelines.html" \
  --work-dir "$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID/verify" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
