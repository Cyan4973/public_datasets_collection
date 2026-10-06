#!/usr/bin/env bash
# Decode RoiResponseSeries/data from the 48 local NWB files into float32 samples.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="dandi_001076_zebrafish_calcium_fluorescence_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

export PYTHONDONTWRITEBYTECODE=1
python3 "$RECIPE_DIR/scripts/selftest_nwb_hdf5.py"
python3 "$RECIPE_DIR/scripts/build_fluorescence.py" build \
  --data-root "$DATA_ROOT" --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
