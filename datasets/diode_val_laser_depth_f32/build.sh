#!/usr/bin/env bash
# Build DIODE validation depth-map samples from the local val.tar.gz only.
# Two streaming passes over the archive (never extracted to disk):
#   1. inventory + size/MD5 check + deterministic overlap-capped view selection
#   2. emit each selected *_depth.npy payload unchanged as raw little-endian float32
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="diode_val_laser_depth_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/diode_depth.py" build --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
