#!/usr/bin/env bash
# Build: decode the 29 locally downloaded N000 DNGs into raw little-endian
# uint16 Bayer CFA mosaics (4048x3036, sensor order, no black subtraction).
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="google_hdrplus_pixel_raw_bayer_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/selftest_lj92.py"
DATA_ROOT="$DATA_ROOT" RECIPE_DIR="$RECIPE_DIR" python3 -I "$RECIPE_DIR/scripts/build_frames.py"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
