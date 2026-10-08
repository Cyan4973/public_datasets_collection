#!/usr/bin/env bash
# Decode the pinned CNC_Machining HDF5 runs (local files only) into one int16
# (n, 3) row-major sample per run, plus the sample index and ingest statistics.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="bosch_cnc_milling_ciss_vibration_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1
python3 "$RECIPE_DIR/scripts/selftest_cnc_h5.py"
python3 "$RECIPE_DIR/scripts/build.py" \
  --repo-root "$REPO_ROOT" --recipe-dir "$RECIPE_DIR" --data-dir "$DATA_DIR"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
