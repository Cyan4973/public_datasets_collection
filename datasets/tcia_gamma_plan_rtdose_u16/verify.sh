#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/tcia_gamma_plan_rtdose_u16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tcia_gamma_plan_rtdose_u16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
python3 "$RECIPE_DIR/scripts/rtdose_volume.py" verify \
  --data-root "$REPO_ROOT/$DATA_DIR"
