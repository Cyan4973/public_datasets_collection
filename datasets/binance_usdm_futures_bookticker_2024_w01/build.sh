#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="binance_usdm_futures_bookticker_2024_w01"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
export REPO_ROOT DATA_DIR
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$REPO_ROOT/tools/binance_archive_recipe.py" build "$REPO_ROOT/datasets/$DATASET_ID/config.json"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
