#!/usr/bin/env bash
# Independently re-derive every sample from the downloaded products and check
# the missing-value policy, index, inventory and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="orex_ola_l2_lidar_point_xyz_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/verify_samples.py" --data-root "$DATA_ROOT" \
  --sources "$RECIPE_DIR/sources.tsv" --manifest "$RECIPE_DIR/manifest.toml" \
  --payload-sha256 "$RECIPE_DIR/payload_sha256.tsv"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
