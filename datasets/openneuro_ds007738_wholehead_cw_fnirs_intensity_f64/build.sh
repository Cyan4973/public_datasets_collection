#!/usr/bin/env bash
# Emit one little-endian float64 sample per resting-state run: the complete
# stored /nirs/data1/dataTimeSeries matrix (time x 1134 channels), from local
# files only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="openneuro_ds007738_wholehead_cw_fnirs_intensity_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

export PYTHONDONTWRITEBYTECODE=1
python3 -I -B "$RECIPE_DIR/scripts/selftest.py"
python3 -I -B "$RECIPE_DIR/scripts/snirf_fnirs.py" build --data-root "$DATA_ROOT" --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
