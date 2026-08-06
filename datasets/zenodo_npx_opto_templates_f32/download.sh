#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/zenodo_npx_opto_templates_f32"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_npx_opto_templates_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/templates.py" download \
  --download-dir "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
