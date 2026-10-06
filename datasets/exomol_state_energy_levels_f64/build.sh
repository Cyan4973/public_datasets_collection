#!/usr/bin/env bash
# Build step for exomol_state_energy_levels_f64; uses local files only.
# Decodes column 2 (state energy, F12.6 cm^-1) of every selected .states.bz2,
# classifies each dataset against the pinned rules, and writes one
# little-endian float64 sample per kept dataset plus the sample index.
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
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

[ -s "$DATA_ROOT/downloads/$DATASET_ID/realized_sha256.tsv" ] || {
  echo "FATAL: run download.sh first (missing realized_sha256.tsv)" >&2
  exit 1
}
python3 "$RECIPE_DIR/scripts/exomol_states.py" build \
  --recipe "$RECIPE_DIR" --data-root "$DATA_ROOT" \
  --workers "${EXOMOL_WORKERS:-16}"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
