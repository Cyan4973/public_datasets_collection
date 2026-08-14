#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="kodak_photo_suite_eval_u8"
EVAL_ROOT="$REPO_ROOT/$DATA_DIR/evaluation/$DATASET_ID"
RECIPE_DIR="$REPO_ROOT/evaluation/$DATASET_ID"
mkdir -p "$EVAL_ROOT/logs"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$EVAL_ROOT/logs/verify.$RUN_TS.log" "$EVAL_ROOT/logs/verify.latest.log") 2>&1
python3 "$RECIPE_DIR/scripts/kodak.py" verify --eval-root "$EVAL_ROOT"
