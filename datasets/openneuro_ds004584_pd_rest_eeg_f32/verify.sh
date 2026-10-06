#!/usr/bin/env bash
# Independently verify the ds004584 resting-state EEG float32 samples.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="openneuro_ds004584_pd_rest_eeg_f32"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ;; *) DATA_DIR="$REPO_ROOT/$DATA_DIR" ;; esac
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_dir=$DATA_DIR"
python3 "$RECIPE_DIR/scripts/verify_ds004584.py" \
  --recipe-dir "$RECIPE_DIR" --data-dir "$DATA_DIR"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
