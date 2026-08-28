#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="alphafold_db_pae_matrices_f32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
LICENSE_URL="https://alphafold.ebi.ac.uk/main-RMCDQW2G.js"
LICENSE_NAME="alphafold_main-RMCDQW2G.js"
LICENSE_BYTES=312610
LICENSE_SHA256="f46325c8ef2d7e156a0f57db06f9be3e7b2eaee3579d63deb9b09033f0a9f1c9"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] pinned download start dataset=$DATASET_ID"

license_target="$DOWNLOAD_DIR/$LICENSE_NAME"
license_cache="$DISCOVERY_DIR/alphafold_main.js"
if [[ ! -f "$license_target" ]] \
  && [[ -f "$license_cache" ]] \
  && [[ "$(stat -c %s "$license_cache")" == "$LICENSE_BYTES" ]] \
  && [[ "$(sha256sum "$license_cache" | awk '{print $1}')" == "$LICENSE_SHA256" ]]; then
  cp "$license_cache" "$license_target"
  echo "reused cached license evidence $LICENSE_NAME"
fi
if [[ ! -f "$license_target" ]] \
  || [[ "$(stat -c %s "$license_target")" != "$LICENSE_BYTES" ]] \
  || [[ "$(sha256sum "$license_target" | awk '{print $1}')" != "$LICENSE_SHA256" ]]; then
  rm -f "$license_target.part"
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 180 --max-filesize "$LICENSE_BYTES" \
    --user-agent "openzl-public-datasets-alphafold-pae-download/1.0" \
    --output "$license_target.part" "$LICENSE_URL"
  if [[ "$(stat -c %s "$license_target.part")" != "$LICENSE_BYTES" ]] \
    || [[ "$(sha256sum "$license_target.part" | awk '{print $1}')" != "$LICENSE_SHA256" ]]; then
    rm -f "$license_target.part"
    echo "AlphaFold DB license evidence changed" >&2
    exit 1
  fi
  mv "$license_target.part" "$license_target"
  echo "downloaded $LICENSE_NAME bytes=$LICENSE_BYTES"
else
  echo "reuse $LICENSE_NAME bytes=$LICENSE_BYTES"
fi

while IFS=$'\t' read -r ordinal accession entry_id version sequence_length source_bytes source_sha256 declared_maximum url; do
  if [[ "$ordinal" == "ordinal" ]]; then
    continue
  fi
  target="$DOWNLOAD_DIR/${ordinal}_${entry_id}_pae_v${version}.json"
  if [[ -f "$target" ]] \
    && [[ "$(stat -c %s "$target")" == "$source_bytes" ]] \
    && [[ "$(sha256sum "$target" | awk '{print $1}')" == "$source_sha256" ]]; then
    echo "reuse $(basename "$target") bytes=$source_bytes accession=$accession"
    continue
  fi
  rm -f "$target.part"
  maximum=$((source_bytes + 1))
  curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-all-errors --max-time 900 --max-filesize "$maximum" \
    --user-agent "openzl-public-datasets-alphafold-pae-download/1.0" \
    --header "Accept: application/json" \
    --output "$target.part" "$url"
  if [[ "$(stat -c %s "$target.part")" != "$source_bytes" ]] \
    || [[ "$(sha256sum "$target.part" | awk '{print $1}')" != "$source_sha256" ]]; then
    rm -f "$target.part"
    echo "source size or hash changed: entry=$entry_id version=$version" >&2
    exit 1
  fi
  mv "$target.part" "$target"
  echo "downloaded $(basename "$target") bytes=$source_bytes accession=$accession length=$sequence_length declared_maximum=$declared_maximum"
done < "$SOURCES"

python3 "$RECIPE_DIR/scripts/pae_matrix.py" validate \
  --sources "$SOURCES" \
  --download-dir "$DOWNLOAD_DIR"

echo "[$(date -Is)] pinned download done dataset=$DATASET_ID"
