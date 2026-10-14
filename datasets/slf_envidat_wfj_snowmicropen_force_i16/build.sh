#!/usr/bin/env bash
# Decode the 291 local S36M .PNT members into little-endian int16 force-count samples (local files only).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="slf_envidat_wfj_snowmicropen_force_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

[[ -d "$DATA_ROOT/downloads/$DATASET_ID/raw_data_members" ]] || {
  echo "missing local members; run download.sh first" >&2
  exit 1
}
python3 -I "$RECIPE_DIR/scripts/build_smp.py" "$DATA_ROOT" "$RECIPE_DIR"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
