#!/usr/bin/env bash
# Build one raw uint8 1381x1381 sample per range-fetched reconstructed axial
# slice of the ESRF ID15 MXene aerogel micro-CT volumes (local files only).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="zenodo_esrf_mxene_aerogel_microct_slices_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

python3 "$RECIPE_DIR/scripts/check_metadata.py" descriptors \
  "$RECIPE_DIR/volumes.tsv" "$DATA_ROOT/downloads/$DATASET_ID/descriptors"
python3 "$RECIPE_DIR/scripts/build_slices.py" \
  --data-root "$DATA_ROOT" \
  --volumes "$RECIPE_DIR/volumes.tsv" \
  --pins "$RECIPE_DIR/slice_sha256.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
