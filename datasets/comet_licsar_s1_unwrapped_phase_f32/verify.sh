#!/usr/bin/env bash
# Independently re-derive every sample from the local rasters (separate decoder
# path), and re-check index fields, no-data policy, non-degeneracy, duplicate
# samples and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="comet_licsar_s1_unwrapped_phase_f32"
case "$DATA_DIR" in /*) LOG_DIR="$DATA_DIR/logs/$DATASET_ID" ;; *) LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID" ;; esac

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/licsar_unw.py" verify \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$RECIPE_DIR/sources.tsv" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
