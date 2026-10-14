#!/usr/bin/env bash
# Fetch 20 pinned raw Kongsberg EM2040 .all files (MB-System id 58) of NOAA Ship
# Rainier survey RICHARD2023L4 from the public anonymous NOAA NODD bucket
# noaa-dcdb-bathymetry-pds. Every file is pinned by size and S3 ETag (5 MiB
# multipart MD5, recomputed locally) and must pass a full datagram scan
# (length, STX, ETX, checksum, model 2040, serial 40129, Y layout).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="noaa_dcdb_rainier_em2040_seabed_image_i16"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/em2040_all.py"
BUCKET="https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com"
PREFIX="mb/ships/rainier/RICHARD2023L4/multibeam/data/version1/MB/em2040/"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID dir=$DOWNLOAD_DIR"

# 1. Current S3 listing of the em2040 folder: every pinned object must still
#    exist with the pinned size and ETag before any payload is fetched.
LISTING="$DOWNLOAD_DIR/listing_RICHARD2023L4_em2040.xml"
curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 300 \
  --output "$LISTING.part" "$BUCKET/?list-type=2&max-keys=1000&prefix=$PREFIX"
python3 -I "$TOOL" listing "$LISTING.part"
mv "$LISTING.part" "$LISTING"

# 2. Remove leftovers that are not pinned (earlier recipe revisions).
mapfile -t PINNED < <(python3 -I "$TOOL" files | awk '{print $1}')
for stale in "$DOWNLOAD_DIR"/*.mb58 "$DOWNLOAD_DIR"/*.mb58.part; do
  [[ -e "$stale" ]] || continue
  base="$(basename "$stale" .part)"
  keep=0
  for name in "${PINNED[@]}"; do
    if [[ "$base" == "$name" ]]; then keep=1; break; fi
  done
  if [[ "$keep" == 0 ]]; then
    echo "removing undeclared leftover $(basename "$stale")"
    rm -f "$stale"
  fi
done

# 3. Pinned payloads: resumable whole-file transfers into .part, then size +
#    ETag + full datagram validation, then rename.
total=0
while read -r name size etag; do
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$size" ]] && python3 -I "$TOOL" etag "$target" --expect "$etag" >/dev/null; then
    echo "validated existing $name"
  else
    rm -f "$target"
    part="$target.part"
    if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$size" ]]; then
      rm -f "$part"
    fi
    if [[ ! -f "$part" || "$(stat -c %s "$part")" -lt "$size" ]]; then
      echo "[$(date -Is)] fetching $name ($size bytes)"
      curl --fail --location --silent --show-error -C - --retry 10 --retry-delay 5 \
        --speed-limit 1024 --speed-time 120 --output "$part" "$BUCKET/$PREFIX$name"
    fi
    actual="$(stat -c %s "$part")"
    if [[ "$actual" != "$size" ]]; then
      echo "size mismatch for $name: $actual != $size" >&2
      exit 1
    fi
    if ! python3 -I "$TOOL" etag "$part" --expect "$etag"; then
      rm -f "$part"
      echo "ETag mismatch for $name; removed partial file" >&2
      exit 1
    fi
    if ! python3 -I "$TOOL" check "$part"; then
      echo "datagram validation failed for $name (ETag matches upstream, so the archived object itself is malformed)" >&2
      exit 1
    fi
    mv "$part" "$target"
  fi
  total=$((total + size))
done < <(python3 -I "$TOOL" files)

echo "pinned payload bytes: $total"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
