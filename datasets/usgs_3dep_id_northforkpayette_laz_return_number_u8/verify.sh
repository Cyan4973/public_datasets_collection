#!/usr/bin/env bash
# Independent verification: re-decode every tile (whole-file decode path),
# re-extract return numbers by a different code path, compare with the
# samples, re-check the header histograms, index fields and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="usgs_3dep_id_northforkpayette_laz_return_number_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/verify_returns.py" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --sources "$RECIPE_DIR/sources.tsv" \
  --data-root "$DATA_ROOT" \
  --laz-dir "$REPO_ROOT/tools/laz" \
  --jobs "${JOBS:-0}"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
