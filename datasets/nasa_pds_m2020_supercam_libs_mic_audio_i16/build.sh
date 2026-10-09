#!/usr/bin/env bash
# Decode the SOUND binary-table HDU of every pinned product (local files only)
# into one raw little-endian uint16 sample per recording.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
[[ "$DATA_DIR" = /* ]] || DATA_DIR="$REPO_ROOT/$DATA_DIR"
CANDIDATE_ID="nasa_pds_m2020_supercam_libs_mic_audio_i16"
SERIES_ID="supercam_mic_libs_100khz_gain2_u16"
LOG_DIR="$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start candidate=$CANDIDATE_ID"

python3 "$RECIPE_DIR/scripts/m2020mic.py" build \
  --sources "$RECIPE_DIR/sources.tsv" \
  --download-dir "$DATA_DIR/downloads/$CANDIDATE_ID" \
  --samples-dir "$DATA_DIR/samples/$CANDIDATE_ID/$SERIES_ID" \
  --index "$DATA_DIR/index/$CANDIDATE_ID/samples.jsonl" \
  --stats "$DATA_DIR/filtered/$CANDIDATE_ID/build_summary.json" \
  --data-root "$DATA_DIR"

echo "[$(date -Is)] build done candidate=$CANDIDATE_ID"
