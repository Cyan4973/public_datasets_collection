#!/usr/bin/env bash
# Build MBARI MARS daily HMD PSD float32 samples from local files only.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ;; *) DATA_DIR="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="mbari_mars_hydrophone_hmd_psd_f32"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/mars_psd.py" build \
  --days "$RECIPE_DIR/days.tsv" \
  --downloads "$DATA_DIR/downloads/$DATASET_ID" \
  --samples-dir "$DATA_DIR/samples/$DATASET_ID" \
  --index "$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_DIR"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
