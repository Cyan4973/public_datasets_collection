#!/usr/bin/env bash
# Verify the GWTC-3 C01:IMRPhenomXPHM posterior-sample columns against local range data only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gwtc3_imrphenomxphm_posterior_samples_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

python3 -I "$RECIPE_DIR/scripts/gwtc3_pe.py" verify \
  --sources "$RECIPE_DIR/sources.tsv" \
  --downloads "$DATA_ROOT/downloads/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_ROOT" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --control "$DATA_ROOT/downloads/$DATASET_ID/control/GW200322_091133.h5"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
