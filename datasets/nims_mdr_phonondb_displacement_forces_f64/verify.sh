#!/usr/bin/env bash
# Independently re-derive every sample from the local .xz files with a second
# parser and check bytes, index, statistics, degeneracy, floors and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nims_mdr_phonondb_displacement_forces_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/phonondb.py" verify \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_ROOT" --sources "$RECIPE_DIR/sources.tsv" \
  --recipe-dir "$RECIPE_DIR"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
