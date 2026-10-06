#!/usr/bin/env bash
# Build one raw uint8 800x540 sample per HC18 ultrasound image from the local
# Zenodo archives (no network access).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_hc18_fetal_head_ultrasound_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

for name in training_set.zip test_set.zip training_set_pixel_size_and_HC.csv test_set_pixel_size.csv; do
  if [ ! -s "$DOWNLOAD_DIR/$name" ]; then
    echo "FATAL: missing $DOWNLOAD_DIR/$name; run download.sh first" >&2
    exit 1
  fi
done

python3 "$RECIPE_DIR/scripts/selftest.py"
python3 "$RECIPE_DIR/scripts/hc18_decode.py" build "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
