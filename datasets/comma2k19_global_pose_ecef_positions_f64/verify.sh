#!/usr/bin/env bash
# Independent verification: re-derive the member set from the downloaded
# central directories, re-inflate every member, re-parse each NPY header,
# compare sample bytes exactly, recheck finiteness / ECEF radius /
# non-degeneracy / uniqueness, and reconcile the index and manifest totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="comma2k19_global_pose_ecef_positions_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/comma2k19_pose.py" verify \
  --downloads "$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID" \
  --samples-dir "$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR" \
  --chunks "$RECIPE_DIR/chunks.tsv" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
