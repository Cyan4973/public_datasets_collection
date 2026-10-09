#!/usr/bin/env bash
# Decode Data.IR of the 96 local HUTUBS measured-HRIR SOFA files into one raw
# little-endian float64 sample per subject (local files only).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hutubs_measured_hrir_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/selftest.py"
python3 -I "$RECIPE_DIR/scripts/hutubs_sofa.py" build \
  --downloads "$DATA_ROOT/downloads/$DATASET_ID" \
  --files-tsv "$RECIPE_DIR/files.tsv" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
