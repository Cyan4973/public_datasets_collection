#!/usr/bin/env bash
# Fetch the 15 pinned NOAA NCEI Water Column Sonar Data Archive EX1711 EM302 .wcd
# files (public anonymous S3, bucket noaa-wcsd-pds) plus the cruise README.
# Every file is pinned by size and S3 ETag (8 MiB multipart MD5, recomputed
# locally) and must pass a full Kongsberg datagram framing/checksum scan.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATASET_ID="noaa_wcsd_em302_water_column_i8"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/em302_wcd.py"
BUCKET="https://noaa-wcsd-pds.s3.amazonaws.com"
PREFIX="data/raw/Okeanos_Explorer/EX1711/EM302/"
README_KEY="data/raw/Okeanos_Explorer/EX1711/README_EX1711_EM302.md"
README_SIZE=2093
README_MD5="a9559a2d5719a14c68b487aefe291e37"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID dir=$DOWNLOAD_DIR"

# 1. Current S3 listing of the cruise EM302 folder: every pinned object must
#    still exist with the pinned size and ETag before any payload is fetched.
LISTING="$DOWNLOAD_DIR/listing_EX1711_EM302.xml"
curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 300 \
  --output "$LISTING.part" "$BUCKET/?list-type=2&prefix=$PREFIX&max-keys=1000"
python3 "$TOOL" listing "$LISTING.part"
mv "$LISTING.part" "$LISTING"

# 2. Cruise README (citation and DOI provenance).
README="$DOWNLOAD_DIR/README_EX1711_EM302.md"
curl --fail --silent --show-error --location --retry 5 --retry-delay 5 --max-time 300 \
  --output "$README.part" "$BUCKET/$README_KEY"
[[ "$(stat -c %s "$README.part")" == "$README_SIZE" ]] || { echo "README size changed" >&2; exit 1; }
[[ "$(md5sum "$README.part" | awk '{print $1}')" == "$README_MD5" ]] || { echo "README MD5 changed" >&2; exit 1; }
grep -q "EX1711" "$README.part" && grep -q "10.7289/V5W957HS" "$README.part" \
  || { echo "README no longer documents EX1711 EM302 / DOI 10.7289/V5W957HS" >&2; exit 1; }
mv "$README.part" "$README"

# 3. Pinned .wcd payloads: resumable whole-file transfers into .part, then
#    size + ETag + full datagram validation, then rename.
mapfile -t PINNED < <(python3 "$TOOL" files | awk '{print $1}')
# Remove leftovers of objects that are no longer pinned (earlier recipe revisions),
# e.g. 0062_20171203_000100, whose archived object ends in a truncated datagram.
for stale in "$DOWNLOAD_DIR"/*.wcd "$DOWNLOAD_DIR"/*.wcd.part; do
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

total=0
while read -r name size etag; do
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$size" ]] && python3 "$TOOL" etag "$target" --expect "$etag" >/dev/null; then
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
    if ! python3 "$TOOL" etag "$part" --expect "$etag"; then
      rm -f "$part"
      echo "ETag mismatch for $name; removed partial file" >&2
      exit 1
    fi
    if ! python3 "$TOOL" check "$part"; then
      echo "datagram validation failed for $name (ETag matches upstream, so the archived object itself is malformed)" >&2
      exit 1
    fi
    mv "$part" "$target"
  fi
  total=$((total + size))
done < <(python3 "$TOOL" files)

echo "pinned payload bytes: $total"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
