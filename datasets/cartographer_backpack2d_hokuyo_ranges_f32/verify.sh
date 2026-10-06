#!/usr/bin/env bash
# Independently re-derive and check the Cartographer backpack_2d Hokuyo range samples.
#
# Re-decodes every bag through its index section (chunk-info -> chunk ->
# index-data offsets) with a separate float-based decoder, compares each scan
# byte-for-byte with the emitted sample, and re-checks index rows, hashes,
# shapes, the range_max sentinel and zero-echo NaN counts, the value domain,
# the 1 mm lattice, scan gaps, nondegeneracy, floors, cap and manifest scope.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="cartographer_backpack2d_hokuyo_ranges_f32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
WORKERS="${WORKERS:-16}"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT workers=$WORKERS"

python3 "$RECIPE_DIR/scripts/cartographer_hokuyo.py" verify \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_ROOT" --sources "$RECIPE_DIR/sources.tsv" --workers "$WORKERS"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
