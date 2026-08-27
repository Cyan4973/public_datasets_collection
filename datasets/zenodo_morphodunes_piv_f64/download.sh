#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_morphodunes_piv_f64"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILES_DIR="$DOWNLOAD_DIR/files"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
RECORD_JSON="$DOWNLOAD_DIR/zenodo_record_16414450.json"
SELECTION="$RECIPE_DIR/selection.tsv"
mkdir -p "$FILES_DIR" "$LOG_DIR"
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

fetch_if_needed "$RECORD_JSON" "https://zenodo.org/api/records/16414450" 5000000
total=0
while IFS=$'\t' read -r experiment condition filename size md5 sha x_count y_count value_count output_sha; do
  url="https://zenodo.org/api/records/16414450/files/$filename/content"
  target="$FILES_DIR/$filename"
  fetch_if_needed "$target" "$url" 10000000
  actual_size="$(stat -c %s "$target")"
  actual_md5="$(md5sum "$target" | awk '{print $1}')"
  actual_sha="$(sha256sum "$target" | awk '{print $1}')"
  [[ "$actual_size" == "$size" && "$actual_md5" == "$md5" && "$actual_sha" == "$sha" ]] || {
    echo "source identity mismatch: $filename" >&2
    exit 1
  }
  total=$((total + actual_size))
  echo "validated file=$filename bytes=$actual_size sha256=$actual_sha"
done < <(tail -n +2 "$SELECTION")
[[ "$total" == "5807387" ]] || { echo "source byte total changed: $total" >&2; exit 1; }
python3 "$RECIPE_DIR/scripts/morphodunes.py" preflight \
  --selection "$SELECTION" --files-dir "$FILES_DIR" --record "$RECORD_JSON"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
