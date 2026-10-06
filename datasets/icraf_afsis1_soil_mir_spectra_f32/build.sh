#!/usr/bin/env bash
# Build one little-endian float32 sample per AfSIS1 soil MIR spectrum from the
# locally downloaded country CSVs. Uses only files under ${DATA_DIR:-.data}.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="icraf_afsis1_soil_mir_spectra_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/afsis_mir.py" check-listing \
  --json "$DATA_ROOT/downloads/$DATASET_ID/dataset_version_1.1.json" \
  --sources "$RECIPE_DIR/sources.tsv"

python3 "$RECIPE_DIR/scripts/afsis_mir.py" build \
  --sources "$RECIPE_DIR/sources.tsv" \
  --csv-dir "$DATA_ROOT/downloads/$DATASET_ID/csv" \
  --data-root "$DATA_ROOT" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
