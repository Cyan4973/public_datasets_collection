#!/usr/bin/env bash
# Local-only build: decode the 20 pinned LAZ tiles with tools/laz/laszip.py and
# emit one raw uint8 LAS return-number array per tile (file point order).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="usgs_3dep_id_northforkpayette_laz_return_number_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/nfp_tiles.py" self-test
python3 -I "$RECIPE_DIR/scripts/nfp_tiles.py" check-all --sources "$RECIPE_DIR/sources.tsv" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" | tail -n 1
python3 -I "$RECIPE_DIR/scripts/build_returns.py" \
  --sources "$RECIPE_DIR/sources.tsv" \
  --data-root "$DATA_ROOT" \
  --laz-dir "$REPO_ROOT/tools/laz" \
  --jobs "${JOBS:-0}"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
