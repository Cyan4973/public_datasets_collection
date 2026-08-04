#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_sanger_abif_i16"
DATA_ROOT="$REPO_ROOT/$DATA_DIR"
LOG_DIR="$DATA_ROOT/logs/$CANDIDATE_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$CANDIDATE_ID"

python3 "$REPO_ROOT/datasets/$CANDIDATE_ID/scripts/abif_trace.py" build \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$CANDIDATE_ID"
