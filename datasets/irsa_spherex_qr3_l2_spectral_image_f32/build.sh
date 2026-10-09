#!/usr/bin/env bash
# Decode the IMAGE extension of each pinned local SPHEREx QR3 L2 prefix into raw little-endian float32.
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
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"
python3 "$RECIPE_DIR/scripts/selftest.py"
python3 "$RECIPE_DIR/scripts/build.py" --data-dir "$DATA_ROOT" --recipe-dir "$RECIPE_DIR"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
