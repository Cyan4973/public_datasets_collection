#!/usr/bin/env bash
# Decode complete EM302 water-column pings from the local pinned .wcd files.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="noaa_wcsd_em302_water_column_i8"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/em302_wcd.py" build \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_ROOT"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
