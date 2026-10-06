#!/usr/bin/env bash
# Independently re-derive every keep/exclude status and every stored double
# from the pinned local sources, then check index, manifest and floors.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hamsci_grape1_wwv10_doppler_frequency_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/grape_wwv10_verify.py" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --sources "$RECIPE_DIR/sources.tsv" \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID/csv_gz" \
  --data-root "$DATA_ROOT" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --classification "$DATA_ROOT/filtered/$DATASET_ID/file_classification.tsv" \
  --workers "${GRAPE_WORKERS:-16}"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
