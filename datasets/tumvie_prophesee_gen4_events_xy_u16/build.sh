#!/usr/bin/env bash
# Build raw little-endian uint16 samples from the locally cached TUM-VIE byte ranges.
# Uses only files under $DATA_DIR/downloads/<id>/ (no network). For each sequence:
# re-resolve the pinned window from the cached HDF5 metadata, decode the 128 Blosc
# chunks of events/x and events/y (zstd CLI + byte unshuffle), check ranges, and
# write one x sample and one y sample of 4,194,304 values each.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="tumvie_prophesee_gen4_events_xy_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

command -v zstd >/dev/null || { echo "FATAL: zstd CLI is required" >&2; exit 1; }
[ -d "$DATA_ROOT/downloads/$DATASET_ID" ] || { echo "FATAL: run download.sh first" >&2; exit 1; }
python3 -I "$RECIPE_DIR/scripts/selftest.py"
python3 -I "$RECIPE_DIR/scripts/tumvie_events.py" build --recipe-dir "$RECIPE_DIR" --data-root "$DATA_ROOT"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
