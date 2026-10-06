#!/usr/bin/env bash
# Independently re-check the output: re-derive the member selection from the
# local central directories and FileInfo.csv, re-decode every member with the
# stdlib zipfile + wave modules (not the build decoder), and compare sample
# bytes, index fields, exclusions, aggregate checksum, floors and manifest
# totals.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="figshare_rousettus_vocalizations_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

python3 "$RECIPE_DIR/scripts/rousettus.py" verify \
  --download-dir "$DATA_ROOT/downloads/$DATASET_ID" \
  --data-root "$DATA_ROOT" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
