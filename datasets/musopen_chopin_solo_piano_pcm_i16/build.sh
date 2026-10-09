#!/usr/bin/env bash
# Decode the 39 pinned Musopen Chopin Prelude/Etude FLAC tracks (local files
# only) into one raw little-endian int16 interleaved-stereo sample per piece.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="musopen_chopin_solo_piano_pcm_i16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DATA_ROOT/samples/$DATASET_ID" "$DATA_ROOT/index/$DATASET_ID" "$DATA_ROOT/filtered/$DATASET_ID"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID data_root=$DATA_ROOT"

command -v ffmpeg >/dev/null 2>&1 || { echo "FATAL: ffmpeg is required to decode FLAC" >&2; exit 1; }
echo "decoder: $(ffmpeg -version | head -n 1)"
python3 -I "$RECIPE_DIR/scripts/musopen_chopin.py" selftest
python3 -I "$RECIPE_DIR/scripts/musopen_chopin.py" build --data-root "$DATA_ROOT"
echo "[$(date -Is)] build done dataset=$DATASET_ID"
