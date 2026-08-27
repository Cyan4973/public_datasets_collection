#!/usr/bin/env bash
# Download and inventory one exact reduced TrackML archive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_trackml_event_truth_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
RECORD="$DOWNLOAD_DIR/record_14386134.json"
ARCHIVE="$DOWNLOAD_DIR/trackml_40k-events-10-to-50-tracks.tar.gz"

mkdir -p "$DOWNLOAD_DIR" "$DISCOVERY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

fetch_if_needed() {
  local target="$1" url="$2" max_bytes="$3"
  if [[ -f "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "reuse existing $(basename "$target") bytes=$(stat -c %s "$target")"
    return
  fi
  local part="$target.part"
  rm -f "$part"
  curl --fail-with-body --silent --show-error --location \
    --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
    --max-time 3600 --max-filesize "$max_bytes" \
    --user-agent "openzl-public-datasets-trackml-f32/1.0" \
    --output "$part" "$url"
  [[ -s "$part" ]] || { echo "empty response for $url" >&2; exit 1; }
  mv "$part" "$target"
}

fetch_if_needed "$RECORD" "https://zenodo.org/api/records/14386134" 20000000
fetch_if_needed "$ARCHIVE" \
  "https://zenodo.org/api/records/14386134/files/trackml_40k-events-10-to-50-tracks.tar.gz/content" \
  200000000

python3 "$RECIPE_DIR/scripts/preflight.py" \
  --selection "$RECIPE_DIR/selection.tsv" --record "$RECORD" \
  --archive "$ARCHIVE" --output-dir "$DISCOVERY_DIR"
echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
