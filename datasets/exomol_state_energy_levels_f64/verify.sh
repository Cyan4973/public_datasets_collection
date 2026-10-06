#!/usr/bin/env bash
# Verify step for exomol_state_energy_levels_f64; uses local files only.
# Re-checks every pinned download hash, re-decodes every selected .states
# file with an independent integer micro-unit parser, re-derives each
# dataset's keep/exclude status, compares every stored double with its source
# token, and checks the index, floors, cap, and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="exomol_state_energy_levels_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$RECIPE_DIR/scripts/exomol_states.py" verify \
  --recipe "$RECIPE_DIR" --data-root "$DATA_ROOT" \
  --workers "${EXOMOL_WORKERS:-16}"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
