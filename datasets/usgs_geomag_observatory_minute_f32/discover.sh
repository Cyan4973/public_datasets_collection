#!/usr/bin/env bash
# Bounded endpoint, schema, and rights preflight.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="usgs_geomag_observatory_minute_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$OUT_DIR/responses" "$OUT_DIR/rights" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1

echo "[$(date -Is)] discovery start candidate=$CANDIDATE_ID"
export OUT_DIR
python3 "$REPO_ROOT/datasets/$CANDIDATE_ID/scripts/discover.py"
echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
