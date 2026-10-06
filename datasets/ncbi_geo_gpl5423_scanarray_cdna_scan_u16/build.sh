#!/usr/bin/env bash
# Build: local files only. Runs the parser self-test, then decodes the 24
# pinned local ScanArray TIFFs into raw little-endian uint16 rasters (one per
# scan, Cy3 and Cy5 in separate series) plus the sample index
# (scripts/scanarray.py build).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ncbi_geo_gpl5423_scanarray_cdna_scan_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$RECIPE_DIR/scripts/scanarray.py" selftest
python3 "$RECIPE_DIR/scripts/scanarray.py" build --data-dir "$DATA_ROOT" --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
