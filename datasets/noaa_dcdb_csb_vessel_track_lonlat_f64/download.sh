#!/usr/bin/env bash
# Fetch the 900 pinned CSB point-data CSV objects (1,172,429,139 bytes) kept
# by selection.tsv from the public NOAA NODD bucket noaa-dcdb-bathymetry-pds.
# Every object is checked against its pinned size and S3 composite ETag
# (5 MiB parts), the exact CSB header, and the first row's
# FILE_UUID/PROVIDER/UNIQUE_ID before it is accepted. Re-runs resume
# partial .part files and skip completed objects.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="noaa_dcdb_csb_vessel_track_lonlat_f64"
BUCKET="https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
CSV_DIR="$DOWNLOAD_DIR/csv"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SELECTION="$RECIPE_DIR/selection.tsv"
SELECTION_SHA256="725be897a641e4b85213188fe90101c4f0b692dd4633cf15961f933a77f30536"
EXPECTED_KEEP_FILES=900
EXPECTED_KEEP_BYTES=1172429139
HELPER=(python3 "$RECIPE_DIR/scripts/csb_tracks.py" --repo-root "$REPO_ROOT"
  --data-dir "$DATA_DIR" --recipe-dir "$RECIPE_DIR")

mkdir -p "$CSV_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

actual_selection_sha="$(sha256sum "$SELECTION" | awk '{print $1}')"
if [[ "$actual_selection_sha" != "$SELECTION_SHA256" ]]; then
  echo "selection.tsv SHA-256 $actual_selection_sha != pinned $SELECTION_SHA256" >&2
  exit 1
fi

first_key="$(awk -F'\t' '$9 == "keep" {print $1; exit}' "$SELECTION")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --output /dev/null "$BUCKET/$first_key"
echo "liveness ok bucket=$BUCKET"

count=0
planned_bytes=0
fetched=0
cached=0
while IFS=$'\t' read -r key size etag last_modified provider unique_id first_time last_time decision reason; do
  [[ "$key" != "key" ]] || continue
  [[ "$decision" == "keep" ]] || continue
  count=$((count + 1))
  planned_bytes=$((planned_bytes + size))
  name="${key##*/}"
  target="$CSV_DIR/$name"
  part="$target.part"
  if [[ -f "$target" ]]; then
    if [[ "$(stat -c %s "$target")" == "$size" ]]; then
      cached=$((cached + 1))
      continue
    fi
    echo "cached size mismatch, refetching file=$name"
    rm -f "$target"
  fi
  if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$size" ]]; then
    rm -f "$part"
  fi
  if [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$size" ]]; then
    curl --fail --silent --show-error --location --continue-at - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --output "$part" "$BUCKET/$key"
  fi
  if ! "${HELPER[@]}" check-object "$part" "$key"; then
    echo "rejecting invalid payload file=$name provider=$provider" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$target"
  fetched=$((fetched + 1))
  if (( (fetched + cached) % 50 == 0 )); then
    echo "progress objects=$((fetched + cached))/$EXPECTED_KEEP_FILES fetched=$fetched cached=$cached"
  fi
done < "$SELECTION"

if [[ "$count" != "$EXPECTED_KEEP_FILES" || "$planned_bytes" != "$EXPECTED_KEEP_BYTES" ]]; then
  echo "unexpected plan: files=$count bytes=$planned_bytes" >&2
  exit 1
fi

"${HELPER[@]}" check-downloads
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$planned_bytes fetched=$fetched cached=$cached"
