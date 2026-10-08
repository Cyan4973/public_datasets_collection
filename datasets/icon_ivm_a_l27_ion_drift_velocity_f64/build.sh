#!/usr/bin/env bash
# Decode the locally cached ICON IVM-A L2-7 ion-velocity chunk spans and emit
# one raw little-endian float64 sample per (UTC day, velocity component).
# Local files only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="icon_ivm_a_l27_ion_drift_velocity_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

export PYTHONDONTWRITEBYTECODE=1
python3 "$RECIPE_DIR/scripts/selftest.py"
python3 "$RECIPE_DIR/scripts/icon_ivm.py" build \
  --downloads "$DATA_ROOT/downloads/$DATASET_ID" \
  --recipe-dir "$RECIPE_DIR" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
