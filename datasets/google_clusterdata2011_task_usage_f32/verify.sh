#!/usr/bin/env bash
# Independently re-derive every window sample from the local source parts and
# check index, stats, manifest totals and the missing-value policy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="google_clusterdata2011_task_usage_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

source "$RECIPE_DIR/scripts/inputs.sh"
for spec in "${INPUTS[@]}"; do
  IFS='|' read -r name size sha <<< "$spec"
  printf '%s  %s\n' "$sha" "$DOWNLOAD_DIR/$name"
done | sha256sum --check --quiet || { echo "VERIFY FAILED: source checksum mismatch" >&2; exit 1; }

SRC_ARGS=()
for name in "${PART_NAMES[@]}"; do SRC_ARGS+=(--source "$DOWNLOAD_DIR/$name"); done
python3 -I "$RECIPE_DIR/scripts/verify_windows.py" \
  --dataset-id "$DATASET_ID" \
  --data-root "$DATA_ROOT" \
  "${SRC_ARGS[@]}" \
  --first-window-s "$FIRST_WINDOW_S" \
  --windows "$WINDOWS" \
  --next-head "$DOWNLOAD_DIR/$NEXT_HEAD_NAME:$NEXT_FIRST_START_US" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
