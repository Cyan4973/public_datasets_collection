#!/usr/bin/env bash
# Download the 88 pinned LiDAR for Scotland Phase I LAZ tiles listed in
# scripts/tiles.tsv (all under the OGL v3 lidar/phase-1/laz/ prefix) and
# validate each one: byte size, S3 ETag (MD5 or 8 MiB multipart MD5), pinned
# sha256 when present, and the LAS/LASzip header layout the build relies on.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="srsp_scotland_phase1_lidar_scan_angle_i8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
TILES="$RECIPE_DIR/scripts/tiles.tsv"
BASE_URL="https://srsp-open-data.s3.eu-west-2.amazonaws.com/"
REQUIRED_PREFIX="lidar/phase-1/laz/"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR/laz"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
exec > >(tee "$LOG_FILE" "$LOG_DIR/download.latest.log") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"
[ -f "$TILES" ] || { echo "missing pinned tile list $TILES" >&2; exit 1; }

# Liveness: one-byte range GET of the first pinned tile.
first_key="$(awk -F'\t' 'NR==2 {print $1}' "$TILES")"
code="$(curl -sS -L -r 0-0 -o /dev/null -w '%{http_code}' --max-time 60 "$BASE_URL$first_key" || true)"
if [ "$code" != "206" ] && [ "$code" != "200" ]; then
  echo "liveness check failed: HTTP $code for $first_key" >&2
  exit 1
fi
echo "liveness ok http=$code key=$first_key"

n=0
while IFS=$'\t' read -r key size etag sha256 _rest; do
  [ "$key" = "key" ] && continue
  [ -n "$key" ] || continue
  case "$key" in
    "$REQUIRED_PREFIX"*.laz) ;;
    *) echo "refusing key outside $REQUIRED_PREFIX (Phase II is Non-Commercial Government Licence): $key" >&2; exit 1 ;;
  esac
  name="$(basename "$key")"
  target="$DOWNLOAD_DIR/laz/$name"
  n=$((n + 1))
  if [ -f "$target" ] && [ "$(stat -c %s "$target")" = "$size" ]; then
    echo "cache_hit [$n] $name bytes=$size"
    continue
  fi
  echo "fetch [$n] $name bytes=$size"
  curl -fL -C - --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
    -o "$target.part" "$BASE_URL$key"
  got="$(stat -c %s "$target.part")"
  if [ "$got" != "$size" ]; then
    echo "size mismatch for $name: got $got expected $size" >&2
    exit 1
  fi
  mv "$target.part" "$target"
done < "$TILES"
echo "fetched_or_cached=$n"

python3 -I "$RECIPE_DIR/scripts/validate_downloads.py" "$TILES" "$DOWNLOAD_DIR" "$REPO_ROOT"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
