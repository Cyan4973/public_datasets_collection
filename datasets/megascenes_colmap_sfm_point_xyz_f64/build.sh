#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="megascenes_colmap_sfm_point_xyz_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/megascenes_points3d.py" selftest
python3 -I "$RECIPE_DIR/scripts/megascenes_points3d.py" build \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" \
  --sources "$RECIPE_DIR/sources.tsv" --expect-files 391

echo "[$(date -Is)] build done dataset=$DATASET_ID"
