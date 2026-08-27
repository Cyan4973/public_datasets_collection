#!/usr/bin/env bash
# License-first metadata discovery for the Zenodo TrackML challenge release.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_trackml_event_truth_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
RECORD_ID="${ZENODO_TRACKML_RECORD_ID:-14386134}"
RECORD_JSON="$OUT_DIR/record_$RECORD_ID.json"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start candidate=$CANDIDATE_ID record=$RECORD_ID"

PART="$RECORD_JSON.part"
rm -f "$PART"
curl --fail-with-body --silent --show-error --location \
  --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
  --max-time 180 --max-filesize 20000000 \
  --user-agent "openzl-public-datasets-trackml-f32-discovery/1.0" \
  --output "$PART" "https://zenodo.org/api/records/$RECORD_ID"
[[ -s "$PART" ]] || { echo "empty Zenodo record response" >&2; exit 1; }
mv "$PART" "$RECORD_JSON"

python3 "$RECIPE_DIR/scripts/discover.py" \
  --record "$RECORD_JSON" --output-dir "$OUT_DIR"
echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
