#!/usr/bin/env bash
# Independently re-derive every sample from the local archives (csv module,
# datetime, Decimal and array('f') instead of the build's fixed-width fast
# path) and check bytes, index statistics, the coverage rule, degeneracy and
# the manifest scope (see scripts/fingrid_frequency.py verify).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="fingrid_nordic_grid_frequency_10hz_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/fingrid_frequency.py" verify --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
