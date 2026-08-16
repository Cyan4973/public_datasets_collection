#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_oisst_weekly_sst_i16_eval"
EVAL_ROOT="$REPO_ROOT/$DATA_DIR/evaluation/$DATASET_ID"
LOG_DIR="$EVAL_ROOT/logs"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] evaluation build start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/oisst_eval.py" build \
  --recipe-dir "$RECIPE_DIR" --eval-root "$EVAL_ROOT"

echo "[$(date -Is)] evaluation build done dataset=$DATASET_ID"
