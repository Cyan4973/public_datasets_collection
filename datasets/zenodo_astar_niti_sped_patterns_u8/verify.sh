#!/usr/bin/env bash
# Independently re-derive and check the ASTAR SPED diffraction pattern
# samples against the pinned local blockfile headers and scan rows (local
# files only).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="zenodo_astar_niti_sped_patterns_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/verify_patterns.py" \
  --data-root "$DATA_ROOT" \
  --pins "$RECIPE_DIR/row_sha256.tsv" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
