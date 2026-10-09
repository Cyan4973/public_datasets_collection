#!/usr/bin/env bash
# Decode the 24 local LiCSAR geo.unw.tif rasters into raw little-endian float32
# samples (one per interferogram) and write the sample index. Local files only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="comet_licsar_s1_unwrapped_phase_f32"
case "$DATA_DIR" in /*) LOG_DIR="$DATA_DIR/logs/$DATASET_ID" ;; *) LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID" ;; esac

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/licsar_unw.py" selftest
python3 -I "$RECIPE_DIR/scripts/licsar_unw.py" build \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$RECIPE_DIR/sources.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
