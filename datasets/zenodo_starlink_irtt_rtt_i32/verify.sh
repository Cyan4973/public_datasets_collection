#!/usr/bin/env bash
# Independently re-derive the IRTT int32 samples from the local archive and check them.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_starlink_irtt_rtt_i32"
ARCHIVE="$DATA_ROOT/downloads/$DATASET_ID/data-20230913-20230917.tar.zst"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

if [ ! -f "$ARCHIVE" ] || [ "$(stat -c %s "$ARCHIVE")" != "1169608066" ]; then
  echo "FATAL: missing or incomplete $ARCHIVE" >&2
  exit 1
fi

python3 -I "$RECIPE_DIR/scripts/irtt_verify.py" --archive "$ARCHIVE" --data-root "$DATA_ROOT" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
