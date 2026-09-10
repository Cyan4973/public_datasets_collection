#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="wwpdb_structure_factors_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
SF_DIR="$DOWNLOAD_DIR/sf"

mkdir -p "$SF_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

while IFS=$'\t' read -r pdb_id url filename size_bytes expected_md5 expected_sha256 reflection_rows amplitude_values sigma_values; do
  [ "$pdb_id" != "pdb_id" ] || continue
  target="$SF_DIR/$filename"
  discovery_cache="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID/headers/$pdb_id.byte"
  if [ ! -s "$target" ] && [ -s "$discovery_cache" ] \
    && [ "$(stat -c %s "$discovery_cache")" = "$size_bytes" ]; then
    cp "$discovery_cache" "$target"
    echo "reused_discovery_payload pdb_id=$pdb_id bytes=$size_bytes"
  fi
  if [ ! -s "$target" ]; then
    echo "fetch pdb_id=$pdb_id url=$url expected_bytes=$size_bytes"
    curl --fail --silent --show-error --location \
      --retry 5 --retry-delay 3 --retry-all-errors \
      --max-time 600 --max-filesize 20000000 \
      --speed-limit 1024 --speed-time 180 \
      --user-agent "openzl-public-datasets-wwpdb-structure-factors/1.0" \
      --output "$target.part" "$url"
    mv "$target.part" "$target"
  else
    echo "cache_hit pdb_id=$pdb_id bytes=$(stat -c %s "$target")"
  fi
  [ "$(stat -c %s "$target")" = "$size_bytes" ] || {
    echo "size mismatch pdb_id=$pdb_id" >&2; exit 1;
  }
  printf '%s  %s\n' "$expected_md5" "$target" | md5sum --check --status
  printf '%s  %s\n' "$expected_sha256" "$target" | sha256sum --check --status
  gzip -t "$target"
  echo "validated pdb_id=$pdb_id bytes=$size_bytes"
done < "$RECIPE_DIR/selection.tsv"

cp "$RECIPE_DIR/selection.tsv" "$DOWNLOAD_DIR/download_plan.tsv"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
