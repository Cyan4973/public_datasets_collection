#!/usr/bin/env bash
# Fully profile the selected TrackML CSV without extracting it to disk.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_trackml_event_truth_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID/trackml_40k-events-10-to-50-tracks.tar.gz"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/profile.$RUN_TS.log" "$LOG_DIR/profile.latest.log") 2>&1
echo "[$(date -Is)] profile start candidate=$CANDIDATE_ID"
python3 "$RECIPE_DIR/scripts/profile.py" --archive "$ARCHIVE" --output-dir "$OUT_DIR"
echo "[$(date -Is)] profile done candidate=$CANDIDATE_ID"
