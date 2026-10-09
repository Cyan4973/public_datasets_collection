#!/usr/bin/env bash
# Independently re-derive the selection and every sample from the local
# members, recompute statistics with a bit-level binary16 conversion, and
# check the policy, index, floors, cap and manifest scope.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="apple_hypersim_normal_cam_f16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"
export PYTHONDONTWRITEBYTECODE=1
python3 -I "$RECIPE_DIR/scripts/verify.py" \
  --repo-root "$REPO_ROOT" --recipe-dir "$RECIPE_DIR" --data-dir "$DATA_ROOT"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
