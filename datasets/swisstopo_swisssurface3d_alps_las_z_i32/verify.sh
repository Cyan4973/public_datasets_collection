#!/usr/bin/env bash
# Independently re-derive every Z sample from the local zips (whole-record
# struct decoding) and check bytes, index, manifest totals and degeneracy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="swisstopo_swisssurface3d_alps_las_z_i32"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"
python3 -I "$RECIPE_DIR/scripts/verify_las_z.py" \
  --sources "$RECIPE_DIR/sources.tsv" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID/zip" \
  --data-root "$DATA_ROOT"
echo "[$(date -Is)] verify done dataset=$DATASET_ID"
