#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_lecroy_oscilloscope_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/inspect.$RUN_TS.log" "$LOG_DIR/inspect.latest.log") 2>&1
echo "[$(date -Is)] full TRC inspection start candidate=$CANDIDATE_ID"

python3 "$REPO_ROOT/datasets/$CANDIDATE_ID/scripts/lecroy_trc.py" inspect \
  --download-dir "$DOWNLOAD_DIR" \
  --output-dir "$OUT_DIR"

echo "[$(date -Is)] full TRC inspection done candidate=$CANDIDATE_ID"
