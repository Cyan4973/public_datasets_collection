#!/usr/bin/env bash
# Metadata-only discovery (not run by build/verify): documents how
# materials.tsv was derived. Fetches the official materials page, then a
# 4 KiB range GET of every listed *_spec.bsdf (header, description, size via
# Content-Range, S3 ETag, Last-Modified), parses the tensor_file headers and
# writes the isotropic subset in materials.tsv layout for diffing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="rgl_epfl_isotropic_spectral_brdf_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
UA="openzl-public-datasets-rgl-brdf-discovery/1.0"

mkdir -p "$OUT_DIR/heads" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start dataset=$DATASET_ID"

curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --retry-all-errors \
  --max-time 180 --max-filesize 5000000 --user-agent "$UA" \
  --output "$OUT_DIR/materials.html" "https://rgl.epfl.ch/materials"

python3 "$RECIPE_DIR/scripts/discover_tsv.py" list "$OUT_DIR/materials.html" > "$OUT_DIR/page_materials.tsv"
echo "page_materials=$(wc -l < "$OUT_DIR/page_materials.tsv")"

while IFS=$'\t' read -r material url <&3; do
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 --retry-all-errors \
    --max-time 60 --range 0-4095 --user-agent "$UA" \
    --dump-header "$OUT_DIR/heads/$material.headers" \
    --output "$OUT_DIR/heads/$material.bin" "$url"
done 3< <(cut -f1,2 "$OUT_DIR/page_materials.tsv")

python3 "$RECIPE_DIR/scripts/discover_tsv.py" table "$OUT_DIR/materials.html" "$OUT_DIR/heads" \
  > "$OUT_DIR/materials.discovered.tsv"
if diff <(cut -f1-4,6- "$RECIPE_DIR/materials.tsv") <(cut -f1-4,6- "$OUT_DIR/materials.discovered.tsv"); then
  echo "discovered isotropic table matches pinned materials.tsv (ignoring sha256)"
else
  echo "WARNING: discovered table differs from pinned materials.tsv" >&2
fi
echo "[$(date -Is)] discovery done dataset=$DATASET_ID"
