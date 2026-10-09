#!/usr/bin/env bash
# Decode local JANUS SimulationArchive files into raw little-endian samples.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_janus_solar_system_integer_phase_space_i64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

rm -rf "$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID" "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/janus_sa.py" selftest
python3 -I "$RECIPE_DIR/scripts/janus_sa.py" build \
  --data-root "$REPO_ROOT/$DATA_DIR" \
  --files "$RECIPE_DIR/scripts/files.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
