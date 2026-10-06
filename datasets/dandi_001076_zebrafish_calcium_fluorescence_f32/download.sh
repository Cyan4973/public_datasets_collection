#!/usr/bin/env bash
# Download the 48 pinned DANDI:001076 NWB files (content-addressed S3 blobs).
#
# DANDI:001076 has no published version, so the recipe pins the draft asset
# set: every blob URL, byte size and dandi:sha2-256 lives in assets.tsv. The
# live draft dandiset.yaml must still declare CC-BY-4.0 / open access, and the
# live draft assets.yaml must list exactly the pinned asset set; any change
# fails the download instead of silently collecting different files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="dandi_001076_zebrafish_calcium_fluorescence_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
META_DIR="$DOWNLOAD_DIR/metadata"
NWB_DIR="$DOWNLOAD_DIR/nwb"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DANDISET_URL="https://dandiarchive.s3.amazonaws.com/dandisets/001076/draft/dandiset.yaml"
ASSETS_URL="https://dandiarchive.s3.amazonaws.com/dandisets/001076/draft/assets.yaml"
EXPECTED_COUNT=48
EXPECTED_BYTES=660278264
UA="openzl-public-datasets-dandi-001076/1.0"

mkdir -p "$META_DIR" "$NWB_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

fetch_small() {
  local url="$1" out="$2"
  rm -f "$out.part"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 2 --retry-all-errors \
    --max-time 180 --max-filesize 5000000 \
    --user-agent "$UA" --output "$out.part" "$url"
  mv "$out.part" "$out"
}

# 1. Live draft metadata: license/identity and the exact pinned asset set.
fetch_small "$DANDISET_URL" "$META_DIR/dandiset.yaml"
fetch_small "$ASSETS_URL" "$META_DIR/assets.yaml"
python3 "$RECIPE_DIR/scripts/dandi_assets.py" license "$META_DIR/dandiset.yaml"
python3 "$RECIPE_DIR/scripts/dandi_assets.py" compare "$META_DIR/assets.yaml" "$RECIPE_DIR/assets.tsv"

# 2. Whole-file blob downloads, resumable, validated by size, SHA-256 and the
#    HDF5 signature before the .part file is promoted.
valid_file() {
  local path="$1" size="$2" sha="$3"
  [[ -f "$path" ]] || return 1
  [[ "$(stat -c %s "$path")" = "$size" ]] || return 1
  [[ "$(head -c 8 "$path" | od -An -tx1 | tr -d ' \n')" = "894844460d0a1a0a" ]] || return 1
  [[ "$(sha256sum "$path" | awk '{print $1}')" = "$sha" ]] || return 1
}

count=0
bytes=0
while IFS=$'\t' read -r asset_path asset_id blob_url size_bytes sha256 _identifier _start _frames _rois _chunks; do
  [[ "$asset_path" != "asset_path" ]] || continue
  name="$(basename "$asset_path")"
  target="$NWB_DIR/$name"
  part="$target.part"
  if valid_file "$target" "$size_bytes" "$sha256"; then
    echo "cache_hit file=$name bytes=$size_bytes"
  else
    rm -f "$target"
    if [[ -f "$part" ]] && (( $(stat -c %s "$part") > size_bytes )); then
      echo "discarding oversized partial file=$name"
      rm -f "$part"
    fi
    attempt=0
    while [[ ! -f "$part" ]] || (( $(stat -c %s "$part") < size_bytes )); do
      attempt=$((attempt + 1))
      if (( attempt > 4 )); then
        echo "FATAL: could not complete $name after $((attempt - 1)) attempts" >&2
        exit 1
      fi
      echo "fetch file=$name asset=$asset_id bytes=$size_bytes attempt=$attempt"
      curl --fail --silent --show-error --location --continue-at - \
        --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 \
        --user-agent "$UA" --output "$part" "$blob_url" || sleep 5
    done
    if ! valid_file "$part" "$size_bytes" "$sha256"; then
      echo "FATAL: $name failed size/HDF5-signature/dandi:sha2-256 validation; partial removed" >&2
      rm -f "$part"
      exit 1
    fi
    mv "$part" "$target"
    echo "validated file=$name bytes=$size_bytes sha256=$sha256"
  fi
  count=$((count + 1))
  bytes=$((bytes + size_bytes))
done < "$RECIPE_DIR/assets.tsv"

if [[ "$count" != "$EXPECTED_COUNT" || "$bytes" != "$EXPECTED_BYTES" ]]; then
  echo "FATAL: unexpected download totals files=$count bytes=$bytes" >&2
  exit 1
fi
stray="$(find "$NWB_DIR" -maxdepth 1 -type f ! -name '*.nwb' -printf '%f\n' | head -5)"
if [[ -n "$stray" ]]; then
  echo "note: non-final files remain in $NWB_DIR: $stray"
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes"
