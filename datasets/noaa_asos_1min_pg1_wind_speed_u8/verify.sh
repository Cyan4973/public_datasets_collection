#!/usr/bin/env bash
# Independent verification: re-derive every sample from the downloads with a
# separate regex parser, compare bytes, index fields, ingest counts and the
# manifest totals, and reject constant or single-value-dominated samples.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="noaa_asos_1min_pg1_wind_speed_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 -I "$RECIPE_DIR/scripts/asos_pg1.py" verify \
  --sources "$RECIPE_DIR/sources.tsv" \
  --data-root "$DATA_ROOT" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
