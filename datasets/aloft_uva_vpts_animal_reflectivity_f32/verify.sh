#!/usr/bin/env bash
# Independently re-derive every eta sample from the local de.tgz and check the
# index, manifest totals, coverage agreement, missing-value policy and
# non-degeneracy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="aloft_uva_vpts_animal_reflectivity_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

printf '%s  %s\n' "77459683bb0d30c16af21ab2d706b260" "$DOWNLOAD_DIR/de.tgz" | md5sum --check --status || {
  echo "FATAL: local de.tgz does not match the pinned MD5" >&2
  exit 1
}
printf '%s  %s\n' "cdc339b008122fcebc9d3414969c07a4" "$DOWNLOAD_DIR/coverage.csv" | md5sum --check --status || {
  echo "FATAL: local coverage.csv does not match the pinned MD5" >&2
  exit 1
}

python3 "$RECIPE_DIR/scripts/verify_vpts.py" \
  --archive "$DOWNLOAD_DIR/de.tgz" \
  --coverage "$DOWNLOAD_DIR/coverage.csv" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
