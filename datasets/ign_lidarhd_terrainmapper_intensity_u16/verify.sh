#!/usr/bin/env bash
# Independent verification: re-decode every pinned tile, re-extract Intensity
# with a separate code path, byte-compare with the samples, and check the
# index, the manifest counts, regime/degeneracy guards and repository floors.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) ROOT="$DATA_DIR" ;; *) ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ign_lidarhd_terrainmapper_intensity_u16"
LOG_DIR="$ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/ign_intensity.py" verify \
  --sources "$RECIPE_DIR/sources.tsv" \
  --data-root "$ROOT" \
  --laz-dir "$REPO_ROOT/tools/laz" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --jobs "${JOBS:-0}"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
