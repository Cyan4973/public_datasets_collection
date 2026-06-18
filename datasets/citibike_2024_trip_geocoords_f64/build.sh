#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="citibike_2024_trip_geocoords_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$REPO_ROOT/tools/numeric64_hunt_recipes.py" build "$DATASET_ID" --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
