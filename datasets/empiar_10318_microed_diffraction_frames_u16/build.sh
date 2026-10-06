#!/usr/bin/env bash
# Build 24 raw little-endian uint16 MicroED diffraction frames (4096x4096) from
# the locally downloaded EMPIAR-10318 ZIP member ranges. Local files only.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="empiar_10318_microed_diffraction_frames_u16"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

if [[ ! -d "$DOWNLOAD_DIR" ]]; then
  echo "ERROR: $DOWNLOAD_DIR missing; run download.sh first" >&2
  exit 1
fi

python3 "$RECIPE_DIR/scripts/microed_smv.py" build \
  --download-dir "$DOWNLOAD_DIR" --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
