#!/usr/bin/env bash
# Build one frame-by-channel float32 voltage-magnitude matrix per pinned PMU
# one-hour CSV, from the local archives only (no network access).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_gridgnosis_pmu_voltage_magnitude_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

for archive in gridgnosis_20308780_steady_state_data.zip grideye_17648863_steady_state_data.zip; do
  if [ ! -s "$DOWNLOAD_DIR/$archive" ]; then
    echo "FATAL: missing $DOWNLOAD_DIR/$archive; run download.sh first" >&2
    exit 1
  fi
done

python3 "$RECIPE_DIR/scripts/build_pmu.py" \
  --members "$RECIPE_DIR/members.tsv" \
  --downloads "$DOWNLOAD_DIR" \
  --data-root "$REPO_ROOT/$DATA_DIR"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
