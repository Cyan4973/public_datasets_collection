#!/usr/bin/env bash
# Download and preflight five commit-pinned EHT UVFITS observations.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="eht_public_uvfits_visibilities_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

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
    --max-time 900 --max-filesize "$max_bytes" \
    --user-agent "openzl-public-datasets-eht-uvfits-f32/1.0" \
    --output "$part" "$url"
  [[ -s "$part" ]] || { echo "empty response for $url" >&2; exit 1; }
  mv "$part" "$target"
}

while IFS=$'\t' read -r source_id repository commit path target size_bytes git_blob_sha sha256 object date_obs hdu_count gcount output_value_count duplicate_ll_count invalid_zero_weight_count invalid_inf_weight_count calibration url; do
  [[ "$source_id" == "source_id" ]] && continue
  fetch_if_needed "$DOWNLOAD_DIR/$target" "$url" 5000000
  license_target="$DOWNLOAD_DIR/${repository}__LICENSE.txt"
  license_url="https://raw.githubusercontent.com/eventhorizontelescope/$repository/$commit/LICENSE.txt"
  fetch_if_needed "$license_target" "$license_url" 2000000
done < "$RECIPE_DIR/selection.tsv"

python3 "$RECIPE_DIR/scripts/uvfits.py" preflight \
  --selection "$RECIPE_DIR/selection.tsv" --download-dir "$DOWNLOAD_DIR" \
  --profile "$DISCOVERY_DIR/uvfits_profile.json"
echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
