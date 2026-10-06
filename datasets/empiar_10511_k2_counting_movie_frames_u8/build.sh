#!/usr/bin/env bash
# Build one raw uint8 3710x3838 sample per pinned K2 movie (frame z = 20) from local files only.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="empiar_10511_k2_counting_movie_frames_u8"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 "$RECIPE_DIR/scripts/k2_movie_frames.py" build \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --data-root "$DATA_ROOT"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
