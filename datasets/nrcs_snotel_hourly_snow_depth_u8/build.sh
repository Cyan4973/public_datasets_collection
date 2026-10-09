#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nrcs_snotel_hourly_snow_depth_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/snotel_snwd.py" selftest
python3 -I "$RECIPE_DIR/scripts/snotel_snwd.py" build \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" \
  --stations "$RECIPE_DIR/sntl_stations_20261009.csv" --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
