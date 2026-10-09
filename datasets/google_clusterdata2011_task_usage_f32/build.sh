#!/usr/bin/env bash
# Build one little-endian float32 sample per complete 5-minute cluster window
# and per task_usage measure (CPU rate, CPI, MAI) from local files only.
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
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

source "$RECIPE_DIR/scripts/inputs.sh"
for spec in "${INPUTS[@]}"; do
  IFS='|' read -r name size sha <<< "$spec"
  f="$DOWNLOAD_DIR/$name"
  [[ -f "$f" ]] || { echo "FATAL: missing $f (run download.sh first)" >&2; exit 1; }
  [[ "$(stat -c %s "$f")" == "$size" ]] || { echo "FATAL: size mismatch for $f" >&2; exit 1; }
  printf '%s  %s\n' "$sha" "$f" | sha256sum --check --status || { echo "FATAL: sha256 mismatch for $f" >&2; exit 1; }
done
echo "inputs ok"

SRC_ARGS=()
for name in "${PART_NAMES[@]}"; do SRC_ARGS+=(--source "$DOWNLOAD_DIR/$name"); done
python3 -I "$RECIPE_DIR/scripts/build_windows.py" \
  --dataset-id "$DATASET_ID" \
  --data-root "$DATA_ROOT" \
  "${SRC_ARGS[@]}" \
  --first-window-s "$FIRST_WINDOW_S" \
  --windows "$WINDOWS" \
  --next-head "$DOWNLOAD_DIR/$NEXT_HEAD_NAME:$NEXT_FIRST_START_US" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
