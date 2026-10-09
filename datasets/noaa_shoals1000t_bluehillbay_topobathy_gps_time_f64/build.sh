#!/usr/bin/env bash
# Local-only build: decode each pinned COPC tile and copy every point's
# float64 GPS time (record bytes 22..29) into one raw little-endian sample.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/shoals_gps_time.py" build \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID/copc" --data-root "$DATA_ROOT"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
