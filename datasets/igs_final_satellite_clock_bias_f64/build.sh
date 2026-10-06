#!/usr/bin/env bash
# Build per-satellite-day float64 clock-bias samples from local IGS final CLK files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="igs_final_satellite_clock_bias_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/igs_clk.py" selftest
python3 "$RECIPE_DIR/scripts/igs_clk.py" build \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$RECIPE_DIR/sources.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
