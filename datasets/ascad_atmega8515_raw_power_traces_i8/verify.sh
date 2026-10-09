#!/usr/bin/env bash
# verify for ascad_atmega8515_raw_power_traces_i8 (local files only).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ascad_atmega8515_raw_power_traces_i8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

RANGE_FILE="$DATA_ROOT/downloads/$DATASET_ID/ATMega8515_raw_traces.h5.deflate_prefix"
TAIL_FILE="$DATA_ROOT/downloads/$DATASET_ID/ASCAD_data.zip.tail4096"
[ -s "$RANGE_FILE" ] || { echo "FATAL: missing $RANGE_FILE; run download.sh" >&2; exit 1; }
[ -s "$TAIL_FILE" ] || { echo "FATAL: missing $TAIL_FILE; run download.sh" >&2; exit 1; }

python3 -I "$RECIPE_DIR/scripts/ascad_traces.py" selftest
python3 -I "$RECIPE_DIR/scripts/ascad_traces.py" check-tail --tail "$TAIL_FILE"
python3 -I "$RECIPE_DIR/scripts/ascad_traces.py" verify --range "$RANGE_FILE" --data-root "$DATA_ROOT"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
