#!/usr/bin/env bash
# Independently re-walk the cached HDF5 metadata, byte-compare every sample
# with its fetched range, recompute the index statistics and the missing-value
# policy, reject degenerate samples, and check the manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="openneuro_ds007738_wholehead_cw_fnirs_intensity_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

export PYTHONDONTWRITEBYTECODE=1
python3 -I -B "$RECIPE_DIR/scripts/selftest.py"
python3 -I -B "$RECIPE_DIR/scripts/verify_fnirs.py" --data-root "$DATA_ROOT" --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
