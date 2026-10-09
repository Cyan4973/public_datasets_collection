#!/usr/bin/env bash
# Independently re-derive and check the TUM-VIE event-window samples (see scripts/verify_events.py).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="tumvie_prophesee_gen4_events_xy_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

command -v zstd >/dev/null || { echo "FATAL: zstd CLI is required" >&2; exit 1; }
python3 -I "$RECIPE_DIR/scripts/selftest.py"
python3 -I "$RECIPE_DIR/scripts/verify_events.py" --recipe-dir "$RECIPE_DIR" --data-root "$DATA_ROOT"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
