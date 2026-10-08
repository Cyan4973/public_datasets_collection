#!/usr/bin/env bash
# Independently re-derive every sample from the local HDF5 files and check the
# index, drop records, floors, cap and manifest scope.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="bosch_cnc_milling_ciss_vibration_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1
python3 "$RECIPE_DIR/scripts/verify.py" \
  --repo-root "$REPO_ROOT" --recipe-dir "$RECIPE_DIR" --data-dir "$DATA_DIR"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
