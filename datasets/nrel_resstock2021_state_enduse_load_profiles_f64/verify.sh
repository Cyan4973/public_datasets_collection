#!/usr/bin/env bash
# Independently re-derive every sample from the downloaded CSVs (separate
# parser, canonical-repr token check, md5 re-check), re-evaluate the end-use
# selection rule with a different rescaling test, and check sample bytes,
# index fields, manifest totals, stray files, degenerate and duplicate
# samples. Uses only files under ${DATA_DIR:-.data}.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="nrel_resstock2021_state_enduse_load_profiles_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/selftest.py"
python3 "$RECIPE_DIR/scripts/resstock_verify.py" \
  --recipe-dir "$RECIPE_DIR" \
  --download-dir "$DOWNLOAD_DIR" \
  --data-root "$DATA_ROOT" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
