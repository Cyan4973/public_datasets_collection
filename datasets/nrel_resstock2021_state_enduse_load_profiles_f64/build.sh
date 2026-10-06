#!/usr/bin/env bash
# Parse the 49 downloaded state CSVs, apply the global end-use selection rule
# (drop an end use if, in any state, it is all +-0, has fewer than 1,000
# distinct values, or is an exact rescaling of another state's series), check
# the result against the pinned keep list in columns.tsv, and write one raw
# little-endian float64 sample per (state, kept end use) plus the sample
# index. Uses only files under ${DATA_DIR:-.data}.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nrel_resstock2021_state_enduse_load_profiles_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

if [ ! -f "$DOWNLOAD_DIR/DOWNLOAD_OK" ]; then
  echo "FATAL: $DOWNLOAD_DIR/DOWNLOAD_OK missing; run download.sh first" >&2
  exit 1
fi
python3 "$RECIPE_DIR/scripts/selftest.py"
python3 "$RECIPE_DIR/scripts/resstock.py" build \
  --recipe-dir "$RECIPE_DIR" \
  --download-dir "$DOWNLOAD_DIR" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
