#!/usr/bin/env bash
# Download and preflight the selected LiBforSecUse complex EIS table.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_battery_eis_complex_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
RECORD="$DOWNLOAD_DIR/zenodo_record_17792537.json"
TABLE="$DOWNLOAD_DIR/frequency-space_spline-interp_v1-3.txt"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch_if_needed() {
  local target="$1" url="$2" max_bytes="$3"
  if [[ -f "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "reuse existing $(basename "$target") bytes=$(stat -c %s "$target")"
    return
  fi
  local part="$target.part"
  rm -f "$part"
  curl --globoff --fail-with-body --silent --show-error --location \
    --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
    --max-time 1800 --max-filesize "$max_bytes" \
    --user-agent "openzl-public-datasets/1.0" --output "$part" "$url"
  [[ -s "$part" ]] || { echo "empty response for $url" >&2; exit 1; }
  mv "$part" "$target"
}

fetch_if_needed "$RECORD" "https://zenodo.org/api/records/17792537" 5000000
fetch_if_needed "$TABLE" \
  "https://zenodo.org/api/records/17792537/files/frequency-space_spline-interp_v1-3.txt/content" \
  20000000

[[ "$(stat -c %s "$TABLE")" == "8139517" ]] || {
  echo "table size mismatch" >&2
  exit 1
}
[[ "$(md5sum "$TABLE" | awk '{print $1}')" == "d8f3abd2a38b4f0c88a6d297ce733264" ]] || {
  echo "table MD5 mismatch" >&2
  exit 1
}
python3 "$RECIPE_DIR/scripts/eis.py" preflight \
  --selection "$RECIPE_DIR/selection.tsv" \
  --record "$RECORD" --table "$TABLE" \
  --profile "$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID/source_profile.json"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
