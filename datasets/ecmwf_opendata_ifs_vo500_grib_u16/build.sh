#!/usr/bin/env bash
# Decode the downloaded vo/500 hPa GRIB2 messages (local files only) into one
# little-endian uint16 packed-code sample per 00z run, plus the sample index.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ecmwf_opendata_ifs_vo500_grib_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/grib2_vo500.py" build "$DATA_ROOT" "$DATASET_ID"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
