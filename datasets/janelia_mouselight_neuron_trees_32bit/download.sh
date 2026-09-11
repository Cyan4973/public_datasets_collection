#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="janelia_mouselight_neuron_trees_32bit"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
SOURCE_DIR="$DOWNLOAD_DIR/swc"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PROBE_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID/payload_probe/swc"
UA="openzl-public-datasets-janelia-mouselight-download/1.0"

mkdir -p "$SOURCE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

: > "$DOWNLOAD_DIR/download_plan.tsv"
printf 'kind\tkey\tfilename\tsize_bytes\tmd5\tsha256\tlast_modified\turl\n' \
  >> "$DOWNLOAD_DIR/download_plan.tsv"

source_count=0
source_bytes=0
while IFS=$'\t' read -r kind key filename size_bytes expected_md5 expected_sha256 last_modified url; do
  [[ "$kind" != "kind" ]] || continue
  target="$SOURCE_DIR/$filename"
  probe_source="$PROBE_DIR/$filename"
  if [[ ! -s "$target" && -s "$probe_source" ]] \
    && [[ "$(stat -c %s "$probe_source")" = "$size_bytes" ]]; then
    cp "$probe_source" "$target"
    echo "reused_probe_payload kind=$kind bytes=$size_bytes file=$filename"
  fi
  if [[ ! -s "$target" ]]; then
    echo "fetch kind=$kind bytes=$size_bytes file=$filename"
    curl --globoff --fail --silent --show-error --location \
      --retry 5 --retry-delay 2 --retry-all-errors --max-time 300 \
      --max-filesize 5000000 --speed-limit 1024 --speed-time 120 \
      --user-agent "$UA" --output "$target.part" "$url"
    mv "$target.part" "$target"
  else
    echo "cache_hit kind=$kind bytes=$(stat -c %s "$target") file=$filename"
  fi
  actual_size="$(stat -c %s "$target")"
  [[ "$actual_size" = "$size_bytes" ]] || {
    echo "size mismatch file=$filename expected=$size_bytes actual=$actual_size" >&2
    exit 1
  }
  printf '%s  %s\n' "$expected_md5" "$target" | md5sum --check --status
  actual_sha256="$(sha256sum "$target" | awk '{print $1}')"
  [[ "$actual_sha256" = "$expected_sha256" ]] || {
    echo "SHA-256 mismatch file=$filename" >&2
    exit 1
  }
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$kind" "$key" "$filename" "$size_bytes" "$expected_md5" \
    "$actual_sha256" "$last_modified" "$url" >> "$DOWNLOAD_DIR/download_plan.tsv"
  source_count=$((source_count + 1))
  source_bytes=$((source_bytes + size_bytes))
done < "$RECIPE_DIR/sources.tsv"

[[ "$source_count" = 320 ]] || {
  echo "unexpected source count: $source_count" >&2
  exit 1
}
[[ "$source_bytes" = 108215773 ]] || {
  echo "unexpected source bytes: $source_bytes" >&2
  exit 1
}

echo "[$(date -Is)] download done dataset=$DATASET_ID files=$source_count bytes=$source_bytes"
