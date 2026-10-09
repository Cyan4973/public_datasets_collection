#!/usr/bin/env bash
# Local-only build: decode the 50 pinned COPC tiles with tools/laz/laszip.py and
# emit one raw uint8 classification-code array per tile (stored point order).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="noaa_coastal_maine_topobathy_classification_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/build_classes.py" \
  --sources "$RECIPE_DIR/sources.tsv" \
  --data-root "$REPO_ROOT/$DATA_DIR" \
  --laz-dir "$REPO_ROOT/tools/laz" \
  --jobs "${JOBS:-0}"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
