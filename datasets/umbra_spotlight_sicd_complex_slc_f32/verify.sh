#!/usr/bin/env bash
# Independently re-derive every sample from the local NITFs (own fixed-offset
# NITF reader, regex SICD XML parse, slice-based byte reversal), byte-compare,
# and check the index, manifest totals, missing-value policy and
# non-degeneracy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="umbra_spotlight_sicd_complex_slc_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/verify.py" --recipe-dir "$RECIPE_DIR" --data-root "$DATA_ROOT"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
