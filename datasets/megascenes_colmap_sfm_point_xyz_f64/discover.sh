#!/usr/bin/env bash
# Documents how sources.tsv was resolved (run 2026-10-09). Not part of the
# download/build path: download.sh uses the pinned sources.tsv only.
# Anonymous S3 ListObjectsV2 over s3://megascenes/reconstruct/000/ (scene IDs
# 000000-000999), following continuation tokens, then keep every
# reconstruct/000/<sss>/colmap/<k>/points3D.bin key with its size and ETag
# (single-part uploads, so ETag == MD5).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="megascenes_colmap_sfm_point_xyz_f64"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
BASE="https://megascenes.s3.us-west-2.amazonaws.com/?list-type=2&prefix=reconstruct/000/&max-keys=1000"

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/page*.xml
cont=""
page=1
while :; do
  url="$BASE"
  if [[ -n "$cont" ]]; then
    enc="$(python3 -I -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$cont")"
    url="$BASE&continuation-token=$enc"
  fi
  curl --fail --silent --show-error --max-time 120 --retry 5 -o "$OUT_DIR/page$page.xml" "$url"
  cont="$(grep -o '<NextContinuationToken>[^<]*' "$OUT_DIR/page$page.xml" | sed 's/<NextContinuationToken>//' || true)"
  echo "page=$page keys=$(grep -o '<KeyCount>[^<]*' "$OUT_DIR/page$page.xml" | sed 's/<KeyCount>//')"
  [[ -n "$cont" ]] || break
  page=$((page + 1))
done

python3 -I "$RECIPE_DIR/scripts/megascenes_points3d.py" plan \
  --out "$OUT_DIR/sources.tsv" "$OUT_DIR"/page*.xml
if diff -q "$OUT_DIR/sources.tsv" "$RECIPE_DIR/sources.tsv" >/dev/null; then
  echo "listing matches pinned sources.tsv"
else
  echo "listing differs from pinned sources.tsv (see $OUT_DIR/sources.tsv)"
fi
