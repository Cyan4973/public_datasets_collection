#!/usr/bin/env bash
# Independently re-derive every sample from the source GRIB2 messages and check
# the index, manifest totals, scope, and non-degeneracy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ecmwf_opendata_ifs_vo500_grib_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/verify_vo500.py" "$DATA_ROOT" "$RECIPE_DIR/manifest.toml"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
