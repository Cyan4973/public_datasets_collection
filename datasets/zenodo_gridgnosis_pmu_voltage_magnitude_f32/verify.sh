#!/usr/bin/env bash
# Independently re-derive every sample from the local archives and check the
# samples, index, missing-value/exclusion policy, and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_gridgnosis_pmu_voltage_magnitude_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/verify_pmu.py" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --members "$RECIPE_DIR/members.tsv" \
  --downloads "$DOWNLOAD_DIR" \
  --data-root "$REPO_ROOT/$DATA_DIR"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
