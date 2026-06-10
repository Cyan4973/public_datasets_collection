#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=ncbi_gene_human
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"

TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/download.$TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
FAILURES="$DOWNLOAD_DIR/download_failures.tsv"
: > "$FAILURES"
exec > >(tee "$LOG_FILE") 2>&1

FORCE_DOWNLOAD=${FORCE_DOWNLOAD:-0}

fetch_human_subset() {
  local key=$1
  local url=$2
  local out=$3
  local tmp="$out.tmp"
  if [[ "$FORCE_DOWNLOAD" != "1" && -s "$out" ]]; then
    echo "cache_hit key=$key path=$out"
    return 0
  fi
  echo "fetch_subset key=$key url=$url"
  rm -f "$tmp"
  if ! curl --fail --location --retry 3 --retry-delay 2 --silent --show-error "$url" \
    | gzip -cd \
    | awk -F '\t' 'NR == 1 || $1 == "9606"' \
    | gzip -c > "$tmp"; then
    echo -e "$key\t$url\tstream_filter_failed" >> "$FAILURES"
    rm -f "$tmp"
    echo "fetch_subset_failed key=$key"
    return 1
  fi
  mv "$tmp" "$out"
  local rows
  rows=$(gzip -cd "$out" | awk 'END{print NR+0}')
  local bytes
  bytes=$(stat -c '%s' "$out")
  echo "fetch_subset_ok key=$key bytes=$bytes rows=$rows"
}

failure_count=0
fetch_human_subset gene_info_human "https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene_info.gz" "$DOWNLOAD_DIR/gene_info_human.tsv.gz" || failure_count=$((failure_count + 1))
fetch_human_subset gene2pubmed_human "https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene2pubmed.gz" "$DOWNLOAD_DIR/gene2pubmed_human.tsv.gz" || failure_count=$((failure_count + 1))

echo "failure_count=$failure_count"
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
if [[ $failure_count -ne 0 ]]; then
  exit 1
fi
