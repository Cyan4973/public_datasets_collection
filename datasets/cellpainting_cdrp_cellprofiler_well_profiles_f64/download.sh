#!/usr/bin/env bash
# Download the 50 pinned CDRP (cpg0012) per-plate CellProfiler profile CSVs from the
# anonymous public Cell Painting Gallery bucket. Only backend/CDRP/<plate>/<plate>.csv
# objects listed in plates.tsv are fetched; the per-plate .sqlite files are never touched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="cellpainting_cdrp_cellprofiler_well_profiles_f64"
BUCKET_BASE="https://cellpainting-gallery.s3.amazonaws.com"
LICENSE_URL="https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/cellpainting-gallery.yaml"
PLATES_TSV="$RECIPE_DIR/plates.tsv"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-cellpainting-cdrp/1.0"

mkdir -p "$DOWNLOAD_DIR/plates" "$DOWNLOAD_DIR/license" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# License evidence: AWS Open Data Registry entry for the Cell Painting Gallery (CC0 1.0).
license_file="$DOWNLOAD_DIR/license/cellpainting-gallery.yaml"
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --retry-all-errors \
  --max-time 120 --max-filesize 1000000 --user-agent "$UA" \
  --output "$license_file.part" "$LICENSE_URL"
mv "$license_file.part" "$license_file"
grep -q '^License: *CC0 1.0 Universal (CC0 1.0) Public Domain Dedication' "$license_file" || {
  echo "FATAL: registry entry no longer states the CC0 1.0 dedication" >&2
  exit 1
}
grep -q 'arn:aws:s3:::cellpainting-gallery' "$license_file" || {
  echo "FATAL: registry entry does not reference the cellpainting-gallery bucket" >&2
  exit 1
}
echo "license_ok=CC0-1.0 source=$LICENSE_URL"

total_expected=0
count=0
while IFS=$'\t' read -r plate size etag last_modified key; do
  [ "$plate" = "plate_id" ] && continue
  [ -z "$plate" ] && continue
  count=$((count + 1))
  total_expected=$((total_expected + size))
  url="$BUCKET_BASE/$key"
  final="$DOWNLOAD_DIR/plates/$plate.csv"
  part="$final.part"

  if [ -f "$final" ] && [ "$(stat -c %s "$final")" = "$size" ]; then
    echo "cache_hit plate=$plate bytes=$size"
  else
    rm -f "$final"
    # Object identity: the pinned ListObjectsV2 ETag (multipart, so not an MD5) and size.
    headers="$(curl --fail --silent --show-error --location --head --retry 5 --retry-delay 2 \
      --retry-all-errors --max-time 60 --user-agent "$UA" "$url")"
    live_etag="$(printf '%s\n' "$headers" | tr -d '\r' | awk 'tolower($1)=="etag:"{print $2}' | tail -n1 | tr -d '"')"
    live_size="$(printf '%s\n' "$headers" | tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}' | tail -n1)"
    if [ "$live_etag" != "$etag" ] || [ "$live_size" != "$size" ]; then
      echo "FATAL: plate $plate object changed upstream: etag=$live_etag size=$live_size pinned etag=$etag size=$size" >&2
      exit 1
    fi
    if [ -f "$part" ] && [ "$(stat -c %s "$part")" -gt "$size" ]; then
      rm -f "$part"
    fi
    if [ ! -f "$part" ] || [ "$(stat -c %s "$part")" != "$size" ]; then
      echo "downloading plate=$plate bytes=$size url=$url"
      curl --fail --location --continue-at - \
        --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 \
        --silent --show-error --user-agent "$UA" --output "$part" "$url"
    fi
    actual="$(stat -c %s "$part")"
    if [ "$actual" != "$size" ]; then
      echo "FATAL: plate $plate size mismatch: expected=$size actual=$actual" >&2
      exit 1
    fi
    mv "$part" "$final"
  fi

  # Semantic validation: pinned 4,725-column header (sha256), field count on every row,
  # Metadata_Plate equals the plate id, unique wells, 300..384 well rows.
  if ! python3 -I "$RECIPE_DIR/scripts/cdrp.py" validate-download \
      --plates "$PLATES_TSV" --downloads "$DOWNLOAD_DIR" --plate "$plate"; then
    echo "FATAL: plate $plate failed semantic validation; removing it" >&2
    rm -f "$final"
    exit 1
  fi
done < "$PLATES_TSV"

if [ "$count" != 50 ]; then
  echo "FATAL: expected 50 pinned plates, found $count" >&2
  exit 1
fi
actual_total="$(stat -c %s "$DOWNLOAD_DIR"/plates/*.csv | awk '{s+=$1} END {print s}')"
if [ "$actual_total" != "$total_expected" ]; then
  echo "FATAL: total bytes $actual_total != pinned $total_expected (stray files?)" >&2
  exit 1
fi
echo "download_ok plates=$count bytes=$actual_total"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
