#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="tcia_cmmd_mammography_u16"
RECIPE_DIR="$REPO_ROOT/staging/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start candidate=$CANDIDATE_ID"

python3 "$RECIPE_DIR/scripts/cmmd_mammography.py" build \
  --download-dir "$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID" \
  --samples-dir "$REPO_ROOT/$DATA_DIR/samples/$CANDIDATE_ID/cmmd_mammography_pixel_u16" \
  --index "$REPO_ROOT/$DATA_DIR/index/$CANDIDATE_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$CANDIDATE_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR"

echo "[$(date -Is)] build done candidate=$CANDIDATE_ID"
