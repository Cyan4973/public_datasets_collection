#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/met_open_access_paintings_u8"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="met_open_access_paintings_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/inspect.$RUN_TS.log" "$LOG_DIR/inspect.latest.log") 2>&1
echo "[$(date -Is)] inspect start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/paintings.py" inspect \
  --download-dir "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
echo "[$(date -Is)] inspect done dataset=$DATASET_ID"
