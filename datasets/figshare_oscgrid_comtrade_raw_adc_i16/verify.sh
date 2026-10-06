#!/usr/bin/env bash
# Independently re-decode the archive, re-parse every dat with a separate
# float-based parser, re-derive the record drop set, and byte-compare every
# emitted sample, index row, and manifest total.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="figshare_oscgrid_comtrade_raw_adc_i16"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

archive="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/Labeled_raw_v1.1.7z"
actual_md5="$(md5sum "$archive" | cut -d' ' -f1)"
if [ "$actual_md5" != "5e15133fd38bf131115897b8737cbf19" ]; then
  echo "FATAL: archive MD5 $actual_md5 does not match the pinned value" >&2
  exit 1
fi
actual_sha256="$(sha256sum "$archive" | cut -d' ' -f1)"
if [ "$actual_sha256" != "33a9fae8e21446b40a3099e6ffa733b679af4f3df4d4ce90aa4b06aeddf45ff8" ]; then
  echo "FATAL: archive SHA-256 $actual_sha256 does not match the pinned value" >&2
  exit 1
fi
echo "archive_hashes=ok md5=$actual_md5 sha256=$actual_sha256"

python3 "$RECIPE_DIR/scripts/oscgrid.py" verify \
  --archive "$archive" \
  --samples-dir "$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID" \
  --index "$REPO_ROOT/$DATA_DIR/index/$DATASET_ID/samples.jsonl" \
  --stats "$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$REPO_ROOT/$DATA_DIR" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
