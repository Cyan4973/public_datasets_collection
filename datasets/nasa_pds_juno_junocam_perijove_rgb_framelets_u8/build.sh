#!/usr/bin/env bash
# Emit one raw uint8 sample per selected JunoCam perijove lossless colour EDR (local files only).
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_juno_junocam_perijove_rgb_framelets_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"
python3 "$RECIPE_DIR/scripts/build.py" --data-dir "$DATA_ROOT" --recipe-dir "$RECIPE_DIR"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
