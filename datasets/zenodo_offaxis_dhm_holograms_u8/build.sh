#!/usr/bin/env bash
# Decode the locally downloaded hologram TIFFs (pure-Python LZW + predictor 2)
# into raw 2048x2048 uint8 samples. Uses only local files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_offaxis_dhm_holograms_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/selftest_tiff.py"
python3 -I "$RECIPE_DIR/scripts/dhm_build.py" --recipe "$RECIPE_DIR" --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
