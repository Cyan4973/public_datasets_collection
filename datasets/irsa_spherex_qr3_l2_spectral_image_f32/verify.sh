#!/usr/bin/env bash
# Independently re-derive every emitted IMAGE sample from the local downloads and check policy and scope.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="irsa_spherex_qr3_l2_spectral_image_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"
python3 "$RECIPE_DIR/scripts/verify.py" --data-dir "$DATA_ROOT" --recipe-dir "$RECIPE_DIR"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
