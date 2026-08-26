#!/usr/bin/env bash
# Exact-record range-only preflight for the CC0 zeolite pressure-series archive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_powder_xrd_patterns_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID/preflight_4955141"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/preflight.$RUN_TS.log" "$LOG_DIR/preflight.latest.log") 2>&1

echo "[$(date -Is)] preflight start candidate=$CANDIDATE_ID record=4955141"
python3 "$REPO_ROOT/datasets/$CANDIDATE_ID/scripts/preflight.py" \
  --output-dir "$OUT_DIR"
echo "[$(date -Is)] preflight done candidate=$CANDIDATE_ID record=4955141"
