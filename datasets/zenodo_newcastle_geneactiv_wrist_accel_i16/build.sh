#!/usr/bin/env bash
# Decode the 13 downloaded GENEActiv member spans (local files only) and emit one
# little-endian int16 interleaved x,y,z sample per left-wrist recording.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_newcastle_geneactiv_wrist_accel_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

PY=(python3 -I "$RECIPE_DIR/scripts/geneactiv.py")
"${PY[@]}" selftest --tmp "$DATA_ROOT/filtered/$DATASET_ID/selftest"
"${PY[@]}" check-cd "$DATA_ROOT/downloads/$DATASET_ID/zip_central_directory.bin" "$RECIPE_DIR/members.tsv"
"${PY[@]}" build --data-root "$DATA_ROOT" --members "$RECIPE_DIR/members.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
