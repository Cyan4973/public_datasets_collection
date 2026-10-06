#!/usr/bin/env bash
# Build one little-endian float64 Freq sample per kept Grape V1 WWV10
# station-day file. Local files only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hamsci_grape1_wwv10_doppler_frequency_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/grape_wwv10.py" \
  --sources "$RECIPE_DIR/sources.tsv" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID/csv_gz" \
  --data-root "$DATA_ROOT" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --filtered-dir "$DATA_ROOT/filtered/$DATASET_ID" \
  --workers "${GRAPE_WORKERS:-16}"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
