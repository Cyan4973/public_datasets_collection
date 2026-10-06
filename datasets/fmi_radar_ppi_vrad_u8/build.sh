#!/usr/bin/env bash
# Build: local files only. Runs the decoder self-test, then decodes the 75
# pinned local scans into raw 2003x2003 uint8 radial-velocity code rasters plus
# the sample index (scripts/fmivrad.py build).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="fmi_radar_ppi_vrad_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$RECIPE_DIR/scripts/fmivrad.py" selftest
python3 "$RECIPE_DIR/scripts/fmivrad.py" build \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_ROOT" --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
