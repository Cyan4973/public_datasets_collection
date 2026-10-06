#!/usr/bin/env bash
# Fetch the 51 pinned isotropic *_spec.bsdf files of the EPFL RGL material
# database plus the two official pages carrying the CC0 grant and the
# material list. Every spec file is checked against its pinned byte size and
# upstream S3 ETag (= MD5 of single-part objects), its pinned SHA-256
# (recorded at the first full download, 2026-10-06), and a semantic
# tensor_file header/payload check before it is kept.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="rgl_epfl_isotropic_spectral_brdf_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
SPEC_DIR="$DOWNLOAD_DIR/spec"
PAGE_DIR="$DOWNLOAD_DIR/pages"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
TOOL="$RECIPE_DIR/scripts/rgl_brdf.py"
MATERIALS_TSV="$RECIPE_DIR/materials.tsv"
LICENSE_URL="https://rgl.epfl.ch/pages/lab/material-database"
MATERIALS_URL="https://rgl.epfl.ch/materials"
EXPECTED_COUNT=51
EXPECTED_BYTES=397553744
UA="openzl-public-datasets-rgl-brdf/1.0"

mkdir -p "$SPEC_DIR" "$PAGE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID expected_files=$EXPECTED_COUNT expected_bytes=$EXPECTED_BYTES"

fetch_page() {
  local url="$1" output="$2"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 2 --retry-all-errors \
    --max-time 180 --max-filesize 5000000 \
    --user-agent "$UA" --output "$output.part" "$url"
  mv "$output.part" "$output"
  echo "page url=$url bytes=$(stat -c %s "$output")"
}

# License and material-list evidence (small; refreshed on every run).
fetch_page "$LICENSE_URL" "$PAGE_DIR/material-database.html"
fetch_page "$MATERIALS_URL" "$PAGE_DIR/materials.html"
python3 "$TOOL" check-pages --materials "$MATERIALS_TSV" \
  --license-page "$PAGE_DIR/material-database.html" \
  --materials-page "$PAGE_DIR/materials.html"

PLAN="$DOWNLOAD_DIR/download_plan.tsv"
printf 'material\tsize_bytes\tmd5_etag\tsha256\turl\n' > "$PLAN.part"

# Liveness: one-byte range GET on the first pinned file.
first_url="$(python3 "$TOOL" plan --materials "$MATERIALS_TSV" | awk -F'\t' 'NR == 1 { print $3 }')"
status="$(curl --silent --show-error --location --max-time 60 --range 0-0 \
  --user-agent "$UA" --output /dev/null --write-out '%{http_code}' "$first_url")"
if [[ "$status" != "206" && "$status" != "200" ]]; then
  echo "FATAL: liveness probe returned HTTP $status for $first_url" >&2
  exit 1
fi
echo "liveness http=$status url=$first_url"

count=0
bytes=0
while IFS=$'\t' read -r material size url <&3; do
  target="$SPEC_DIR/${material}_spec.bsdf"
  part="$target.part"
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$size" ]]; then
    candidate="$target"
    echo "cache_hit material=$material bytes=$size"
  else
    rm -f "$target"
    if [[ -f "$part" && "$(stat -c %s "$part")" -gt "$size" ]]; then
      rm -f "$part"
    fi
    if [[ ! -f "$part" || "$(stat -c %s "$part")" != "$size" ]]; then
      echo "fetch material=$material bytes=$size"
      curl --fail --silent --show-error --location --continue-at - \
        --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 --max-filesize 30000000 \
        --user-agent "$UA" --output "$part" "$url"
    fi
    candidate="$part"
  fi
  if ! sha256="$(python3 "$TOOL" check-file --materials "$MATERIALS_TSV" --material "$material" --path "$candidate")"; then
    echo "FATAL: semantic validation failed for $material; removing $candidate" >&2
    rm -f "$candidate"
    exit 1
  fi
  if [[ "$candidate" == "$part" ]]; then
    mv "$part" "$target"
  fi
  md5="$(md5sum "$target" | cut -d' ' -f1)"
  printf '%s\t%s\t%s\t%s\t%s\n' "$material" "$size" "$md5" "$sha256" "$url" >> "$PLAN.part"
  echo "ok material=$material bytes=$size md5=$md5 sha256=$sha256"
  count=$((count + 1))
  bytes=$((bytes + size))
done 3< <(python3 "$TOOL" plan --materials "$MATERIALS_TSV")

if [[ "$count" != "$EXPECTED_COUNT" || "$bytes" != "$EXPECTED_BYTES" ]]; then
  echo "FATAL: realized files=$count bytes=$bytes, expected files=$EXPECTED_COUNT bytes=$EXPECTED_BYTES" >&2
  exit 1
fi
mv "$PLAN.part" "$PLAN"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$bytes plan=$PLAN"
