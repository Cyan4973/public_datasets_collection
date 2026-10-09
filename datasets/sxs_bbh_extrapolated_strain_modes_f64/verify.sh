#!/usr/bin/env bash
# Verify the SXS:BBH Extrapolated_N2 l<=4 strain-mode samples against local range blocks only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="sxs_bbh_extrapolated_strain_modes_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

python3 -I "$RECIPE_DIR/scripts/sxs_modes.py" verify \
  --sims "$RECIPE_DIR/sims.tsv" \
  --downloads "$DATA_ROOT/downloads/$DATASET_ID" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_ROOT" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --control "$DATA_ROOT/downloads/$DATASET_ID/control/SXS_BBH_1180.h5"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
