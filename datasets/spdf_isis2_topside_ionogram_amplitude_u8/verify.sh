#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="spdf_isis2_topside_ionogram_amplitude_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

# Re-decodes every pinned CDF, re-applies the completeness rule, and checks
# sample bytes, index rows, degeneracy guards and manifest totals.
python3 -I -B "$RECIPE_DIR/scripts/isis2_ionogram.py" verify \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$RECIPE_DIR/sources.tsv" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
