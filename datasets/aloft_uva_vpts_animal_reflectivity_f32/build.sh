#!/usr/bin/env bash
# Decode every German radar-month VPTS member of the local de.tgz into one
# little-endian float32 (profile x 25 heights) eta matrix. Local files only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="aloft_uva_vpts_animal_reflectivity_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

for required in de.tgz coverage.csv; do
  if [ ! -s "$DOWNLOAD_DIR/$required" ]; then
    echo "FATAL: missing $DOWNLOAD_DIR/$required; run download.sh first" >&2
    exit 1
  fi
done

python3 "$RECIPE_DIR/scripts/vpts.py" build \
  --archive "$DOWNLOAD_DIR/de.tgz" \
  --coverage "$DOWNLOAD_DIR/coverage.csv" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
