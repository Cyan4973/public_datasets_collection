#!/usr/bin/env bash
# Independently re-derive the selection from the cached central directories,
# re-inflate every member, byte-compare each sample, re-check the
# missing-value policy (non-finite values are fatal), reject constant or
# degenerate frames, and check the index against manifest.toml.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tartanair_optical_flow_f32"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/tartanair_flow.py" verify \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$RECIPE_DIR/sources.tsv" \
  --manifest "$RECIPE_DIR/manifest.toml"
if [[ -f "$RECIPE_DIR/selection.lock.tsv" ]]; then
  cmp "$RECIPE_DIR/selection.lock.tsv" "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/selection.tsv"
  echo "selection matches selection.lock.tsv"
fi

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
