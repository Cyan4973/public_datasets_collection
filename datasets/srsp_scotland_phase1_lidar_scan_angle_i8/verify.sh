#!/usr/bin/env bash
# Independent verification: re-derive every sample from its local LAZ tile and
# re-check typing, degeneracy, floors, and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="srsp_scotland_phase1_lidar_scan_angle_i8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
WORKERS="${SRSP_WORKERS:-$(python3 -c 'import os; print(min(16, os.cpu_count() or 1))')}"
mkdir -p "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/verify.$RUN_TS.log"
exec > >(tee "$LOG_FILE" "$LOG_DIR/verify.latest.log") 2>&1

echo "[$(date -Is)] verify start dataset=$DATASET_ID workers=$WORKERS"
python3 -I "$RECIPE_DIR/scripts/verify_samples.py" "$RECIPE_DIR" "$DATA_ROOT" "$REPO_ROOT" "$WORKERS"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
