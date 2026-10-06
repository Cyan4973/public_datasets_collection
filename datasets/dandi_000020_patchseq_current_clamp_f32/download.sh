#!/usr/bin/env bash
# Download the pinned DANDI:000020 0.210913.1639 metadata and the selected NWB blobs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="dandi_000020_patchseq_current_clamp_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
NWB_DIR="$DOWNLOAD_DIR/nwb"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/patchseq_cc.py"
SOURCES="$RECIPE_DIR/sources.tsv"
BASE_URL="https://dandiarchive.s3.amazonaws.com/dandisets/000020/0.210913.1639"
ASSETS_YAML_BYTES=11176113
UA="openzl-public-datasets-dandi000020/1.0"
EXPECTED_FILES=16
EXPECTED_BYTES=521558599

mkdir -p "$NWB_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch_small() {
  local url="$1" target="$2" max_bytes="$3"
  if [ ! -s "$target" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    rm -f "$target.part"
    curl --fail --silent --show-error --location \
      --retry 5 --retry-delay 3 --retry-all-errors \
      --max-time 600 --max-filesize "$max_bytes" \
      --user-agent "$UA" --output "$target.part" "$url"
    mv "$target.part" "$target"
  fi
}

# 1. Pinned dandiset metadata: identity, CC-BY-4.0 license, open access.
fetch_small "$BASE_URL/dandiset.yaml" "$DOWNLOAD_DIR/dandiset.yaml" 100000
python3 "$TOOL" check-dandiset --dandiset-yaml "$DOWNLOAD_DIR/dandiset.yaml"

# 2. Pinned asset manifest (size + SHA-256 checked by the parser).
fetch_small "$BASE_URL/assets.yaml" "$DOWNLOAD_DIR/assets.yaml" "$((ASSETS_YAML_BYTES + 1024))"

# 3. The committed selection must equal the documented rule applied to assets.yaml.
python3 "$TOOL" check-sources --assets-yaml "$DOWNLOAD_DIR/assets.yaml" --sources "$SOURCES"

# 4. Selected NWB blobs: resumable, stall-bounded, size- and SHA-256-verified.
file_count=0
byte_count=0
while IFS=$'\t' read -r rank subject_id asset_path asset_id size_bytes sha256 url local_name; do
  [ "$rank" != "rank" ] || continue
  target="$NWB_DIR/$local_name"
  if [ -s "$target" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if python3 "$TOOL" check-file --file "$target" --size "$size_bytes" --sha256 "$sha256" < /dev/null; then
      echo "cache_hit $asset_path"
      file_count=$((file_count + 1))
      byte_count=$((byte_count + size_bytes))
      continue
    fi
    echo "invalid cached file, refetching: $asset_path"
    rm -f "$target"
  fi
  [ "${FORCE_DOWNLOAD:-0}" != "1" ] || rm -f "$target.part"
  part_size=0
  [ ! -f "$target.part" ] || part_size="$(stat -c %s "$target.part")"
  if [ "$part_size" -gt "$size_bytes" ]; then
    echo "oversized partial file, restarting: $asset_path"
    rm -f "$target.part"
    part_size=0
  fi
  if [ "$part_size" -lt "$size_bytes" ]; then
    echo "fetch $asset_path bytes=$size_bytes resume_from=$part_size url=$url"
    curl --fail --silent --show-error --location \
      --continue-at - --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --max-filesize "$((size_bytes + 1024))" \
      --user-agent "$UA" --output "$target.part" "$url" < /dev/null
  fi
  actual_size="$(stat -c %s "$target.part")"
  if [ "$actual_size" != "$size_bytes" ]; then
    echo "FATAL: size mismatch for $asset_path expected=$size_bytes actual=$actual_size" >&2
    exit 1
  fi
  mv "$target.part" "$target"
  python3 "$TOOL" check-file --file "$target" --size "$size_bytes" --sha256 "$sha256" < /dev/null
  file_count=$((file_count + 1))
  byte_count=$((byte_count + size_bytes))
done < "$SOURCES"

if [ "$file_count" != "$EXPECTED_FILES" ] || [ "$byte_count" != "$EXPECTED_BYTES" ]; then
  echo "FATAL: unexpected totals files=$file_count bytes=$byte_count" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$file_count bytes=$byte_count"
