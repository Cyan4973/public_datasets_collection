#!/usr/bin/env bash
# Local-only verify: decode the 48 pinned COPC tiles with tools/laz/laszip.py
# and independently re-derive and byte-compare every stored intensity sample.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_ngs_potomac_topobathy_vq880g_intensity_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/verify_intensity.py" \
  --recipe-dir "$RECIPE_DIR" \
  --data-root "$DATA_ROOT" \
  --laz-dir "$REPO_ROOT/tools/laz" \
  --jobs "${JOBS:-0}"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
