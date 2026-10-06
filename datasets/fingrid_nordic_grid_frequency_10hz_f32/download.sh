#!/usr/bin/env bash
# Download the three pinned Fingrid monthly 10 Hz frequency archives
# (2025-01, 2025-07, 2026-01; ~200 MB total) after re-validating the dataset
# page's CC BY 4.0 license and file listing.  Each archive is fetched whole
# (solid 7z), resumably, then checked for size, Azure Content-MD5, the pinned
# 7z member list, and a full decode with every member's CRC32 before it is
# renamed into place.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="fingrid_nordic_grid_frequency_10hz_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
PAGE_URL="https://data.fingrid.fi/en/datasets/339"
TOOL="$RECIPE_DIR/scripts/fingrid_frequency.py"
UA="openzl-public-datasets-fingrid-frequency/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# 1. License and listing: the dataset page embeds its metadata as JSON.
page="$DOWNLOAD_DIR/dataset_339.html"
curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --retry-connrefused \
  --max-time 180 --max-filesize 10000000 --user-agent "$UA" \
  --output "$page.part" "$PAGE_URL"
mv "$page.part" "$page"
python3 "$TOOL" check-page --page "$page"

# 2. Archives.
while IFS=$'\t' read -r -u 3 month filename url size_bytes content_md5 last_modified sha256; do
  [ -n "$month" ] || continue
  final="$DOWNLOAD_DIR/$filename"
  part="$final.part"
  echo "[$(date -Is)] archive month=$month url=$url bytes=$size_bytes content_md5=$content_md5 last_modified='$last_modified'"

  if [ -f "$final" ]; then
    if python3 "$TOOL" validate-download --quick --month "$month" --archive "$final"; then
      echo "cache_hit month=$month path=$final"
      continue
    fi
    echo "cached archive failed validation; re-downloading month=$month"
    rm -f "$final"
  fi

  if [ -f "$part" ] && [ "$(stat -c %s "$part")" -gt "$size_bytes" ]; then
    echo "partial file larger than the pinned size; restarting month=$month"
    rm -f "$part"
  fi

  # Liveness: one-byte range GET.
  code="$(curl --silent --show-error --location --max-time 60 --user-agent "$UA" \
    --range 0-0 --output /dev/null --write-out '%{http_code}' "$url" || true)"
  if [ "$code" != "206" ] && [ "$code" != "200" ]; then
    echo "FATAL: liveness check for $url returned HTTP $code" >&2
    exit 1
  fi

  attempt=0
  while :; do
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    [ "$have" -eq "$size_bytes" ] && break
    attempt=$((attempt + 1))
    if [ "$attempt" -gt 8 ]; then
      echo "FATAL: $url still incomplete after $((attempt - 1)) attempts ($have/$size_bytes bytes)" >&2
      exit 1
    fi
    echo "curl attempt=$attempt resume_from=$have"
    curl --fail --location --show-error --silent \
      --continue-at - --retry 10 --retry-delay 5 --retry-connrefused \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$part" "$url" || sleep 10
  done

  if ! python3 "$TOOL" validate-download --month "$month" --archive "$part"; then
    echo "FATAL: $filename failed payload validation; removing the partial file" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$final"
done 3< <(tail -n +2 "$RECIPE_DIR/sources.tsv")

# Checksums of the pinned archives only (archives from earlier recipe
# revisions, if any, are left untouched and ignored by build/verify).
pinned_files=()
while IFS=$'\t' read -r -u 3 _month filename _rest; do
  [ -n "$filename" ] && pinned_files+=("$filename")
done 3< <(tail -n +2 "$RECIPE_DIR/sources.tsv")
( cd "$DOWNLOAD_DIR" && sha256sum "${pinned_files[@]}" > SHA256SUMS && cat SHA256SUMS )
du -cb "${pinned_files[@]/#/$DOWNLOAD_DIR/}" | tail -1
echo "[$(date -Is)] download done dataset=$DATASET_ID"
