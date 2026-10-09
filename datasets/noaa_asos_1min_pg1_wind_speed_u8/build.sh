#!/usr/bin/env bash
# Local-only build: parse the downloaded DSI 6405 station-month files and emit
# one uint8 sample per station-month for each wind-speed series.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_asos_1min_pg1_wind_speed_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/asos_pg1.py" build \
  --sources "$RECIPE_DIR/sources.tsv" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
