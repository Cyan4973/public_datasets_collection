#!/usr/bin/env bash
# Independently re-derive every sample from the cached spans, re-check the
# missing-value policy, degeneracy, index fields, control-file equality and
# manifest totals. Local files only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="icon_ivm_a_l27_ion_drift_velocity_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

export PYTHONDONTWRITEBYTECODE=1
python3 "$RECIPE_DIR/scripts/selftest.py"
python3 "$RECIPE_DIR/scripts/verify_samples.py" \
  --downloads "$DATA_ROOT/downloads/$DATASET_ID" \
  --recipe-dir "$RECIPE_DIR" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
