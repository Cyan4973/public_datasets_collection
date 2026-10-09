#!/usr/bin/env bash
# Fetch the 391 pinned MegaScenes points3D.bin files listed in sources.tsv
# (s3://megascenes/reconstruct/000/*/colmap/*/points3D.bin, 445,121,839 bytes)
# over anonymous HTTPS. Each file is checked for exact size, MD5 (== S3 ETag),
# and a full COLMAP points3D.bin parse that must end exactly at EOF.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="megascenes_colmap_sfm_point_xyz_f64"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
SOURCE_DIR="$DOWNLOAD_DIR/points3d"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PARSER="$RECIPE_DIR/scripts/megascenes_points3d.py"
UA="openzl-public-datasets-megascenes-download/1.0"
EXPECT_FILES=391
EXPECT_BYTES=445121839

mkdir -p "$SOURCE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

python3 -I "$PARSER" selftest

# Liveness: one-byte range GET on the first pinned object.
first_url="$(awk -F'\t' 'NR==2 {print $6}' "$RECIPE_DIR/sources.tsv")"
curl --fail --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null "$first_url"

count=0
total=0
while IFS=$'\t' read -r key filename size_bytes md5 last_modified url; do
  [[ "$key" != "key" ]] || continue
  target="$SOURCE_DIR/$filename"
  if [[ -f "$target" && "$(stat -c %s "$target")" = "$size_bytes" ]]; then
    echo "cache_hit bytes=$size_bytes key=$key"
  else
    echo "fetch bytes=$size_bytes key=$key"
    curl --globoff --fail --silent --show-error --location -C - \
      --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$target.part" "$url"
    mv "$target.part" "$target"
  fi
  actual="$(stat -c %s "$target")"
  if [[ "$actual" != "$size_bytes" ]]; then
    echo "size mismatch key=$key expected=$size_bytes actual=$actual" >&2
    rm -f "$target"
    exit 1
  fi
  if ! printf '%s  %s\n' "$md5" "$target" | md5sum --check --status; then
    echo "MD5 mismatch key=$key" >&2
    rm -f "$target"
    exit 1
  fi
  if ! python3 -I "$PARSER" check "$target" >/dev/null; then
    echo "points3D.bin parse failed key=$key" >&2
    exit 1
  fi
  count=$((count + 1))
  total=$((total + actual))
done < "$RECIPE_DIR/sources.tsv"

[[ "$count" = "$EXPECT_FILES" ]] || { echo "unexpected file count $count" >&2; exit 1; }
[[ "$total" = "$EXPECT_BYTES" ]] || { echo "unexpected byte total $total" >&2; exit 1; }
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$total"
