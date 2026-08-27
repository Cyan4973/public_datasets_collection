#!/usr/bin/env bash
# Download, validate, and preflight five official WMAP HEALPix band maps.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="nasa_wmap_healpix_sky_maps_f32"
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
  local errors="$part.stderr"
  rm -f "$part" "$errors"
  if ! curl --globoff --fail-with-body --silent --show-error --location \
    --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
    --max-time 3600 --max-filesize "$max_bytes" \
    --user-agent "openzl-public-datasets-wmap-healpix-f32/1.0" \
    --output "$part" "$url" 2>"$errors"; then
    cat "$errors" >&2
    exit 1
  fi
  rm -f "$errors"
  [[ -s "$part" ]] || { echo "empty response for $url" >&2; exit 1; }
  mv "$part" "$target"
}

fetch_if_needed "$DOWNLOAD_DIR/wmap_products.html" \
  "https://lambda.gsfc.nasa.gov/product/wmap/dr5/m_products.html" 5000000
fetch_if_needed "$DOWNLOAD_DIR/nasa_media_usage.html" \
  "https://www.nasa.gov/nasa-brand-center/images-and-media/" 5000000

while IFS=$'\t' read -r band filename size_bytes source_sha256 url; do
  [[ "$band" == "band" ]] && continue
  fetch_if_needed "$DOWNLOAD_DIR/$filename" "$url" 110000000
  [[ "$(stat -c %s "$DOWNLOAD_DIR/$filename")" == "$size_bytes" ]] || {
    echo "$band source size mismatch" >&2
    exit 1
  }
done < "$RECIPE_DIR/selection.tsv"

python3 "$RECIPE_DIR/scripts/wmap.py" preflight \
  --selection "$RECIPE_DIR/selection.tsv" --download-dir "$DOWNLOAD_DIR" \
  --profile "$DISCOVERY_DIR/full_source_profile.json"
echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
