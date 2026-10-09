#!/usr/bin/env bash
# Decode the downloaded Hypersim normal_cam HDF5 members (local files only)
# into one raw little-endian float16 [768, 1024, 3] sample per frame, plus the
# sample index and filtered/<id>/build_stats.json.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="apple_hypersim_normal_cam_f16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"
export PYTHONDONTWRITEBYTECODE=1
python3 -I "$RECIPE_DIR/scripts/selftest.py"
python3 -I "$RECIPE_DIR/scripts/build.py" \
  --repo-root "$REPO_ROOT" --recipe-dir "$RECIPE_DIR" --data-dir "$DATA_ROOT"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
