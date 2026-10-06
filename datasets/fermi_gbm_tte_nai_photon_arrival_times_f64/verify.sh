#!/usr/bin/env bash
# Independently re-decode every pinned GBM TTE file (separate parser in
# scripts/verify_tte.py) and check byte equality with the emitted samples,
# time ordering and span, index statistics, sample inventory, manifest totals
# and degeneracy rules.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="fermi_gbm_tte_nai_photon_arrival_times_f64"
SERIES_ID="gbm_nai_tte_photon_time_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/verify_tte.py" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --sources "$RECIPE_DIR/sources.tsv" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID/$SERIES_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
