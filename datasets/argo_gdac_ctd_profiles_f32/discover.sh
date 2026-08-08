#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="argo_gdac_ctd_profiles_f32"
OUTPUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
mkdir -p "$OUTPUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1

echo "[$(date -Is)] discovery start candidate=$CANDIDATE_ID"
python3 "$REPO_ROOT/datasets/$CANDIDATE_ID/scripts/discover.py" \
  --output-dir "$OUTPUT_DIR"
echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
