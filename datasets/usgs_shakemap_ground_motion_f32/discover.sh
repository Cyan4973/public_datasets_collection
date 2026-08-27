#!/usr/bin/env bash
# Metadata-only discovery of official USGS ShakeMap raster products.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="usgs_shakemap_ground_motion_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$OUT_DIR/events" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start candidate=$CANDIDATE_ID"
python3 "$RECIPE_DIR/scripts/discover.py" --output-dir "$OUT_DIR"
echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
