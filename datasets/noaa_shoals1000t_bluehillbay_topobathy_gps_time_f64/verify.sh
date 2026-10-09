#!/usr/bin/env bash
# Independent verification: re-decode every tile, re-extract GPS time with a
# different code path (struct.iter_unpack), byte-compare with the samples,
# re-check the index, COPC/STAC cross-checks, non-constancy, and the manifest
# sample_count / total_size_bytes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/shoals_gps_time.py" verify \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID/copc" --data-root "$DATA_ROOT"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
