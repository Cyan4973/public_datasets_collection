#!/usr/bin/env bash
# Build per-orbit little-endian int32 samples (kept-spot lunar radius and
# kept-spot two-way laser range, millimetres) from the 28 pinned LOLA RDR
# orbit products. Uses only files already under
# $DATA_DIR/downloads/nasa_pds_lola_rdr_spot_radius_range_i32/.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nasa_pds_lola_rdr_spot_radius_range_i32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/lola_rdr.py" self-test
python3 -I "$RECIPE_DIR/scripts/build_samples.py" --data-root "$DATA_ROOT" --sources "$RECIPE_DIR/sources.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
