#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="globalcmt_catalog_f64"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
SOURCE_URL="https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/jan76_dec20.ndk"
SOURCE_FILE="$DOWNLOAD_DIR/jan76_dec20.ndk"
MAX_SOURCE_BYTES=200000000

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [[ ! -s "$SOURCE_FILE" ]]; then
  tmp="$SOURCE_FILE.part"
  rm -f "$tmp"
  curl --fail --location --retry 3 --retry-delay 2 \
    --user-agent "openzl-public-datasets/1.0" \
    --max-filesize "$MAX_SOURCE_BYTES" \
    --output "$tmp" "$SOURCE_URL"
  mv "$tmp" "$SOURCE_FILE"
else
  echo "reuse existing source $SOURCE_FILE"
fi

size="$(wc -c < "$SOURCE_FILE" | tr -d ' ')"
if (( size < 1000000 || size > MAX_SOURCE_BYTES )); then
  echo "unexpected source size: $size bytes" >&2
  exit 1
fi

python3 "$REPO_ROOT/datasets/$DATASET_ID/scripts/globalcmt_ndk.py" \
  inspect "$SOURCE_FILE"

sha256="$(sha256sum "$SOURCE_FILE" | awk '{print $1}')"
printf 'source_url\tlocal_name\tbytes\tsha256\n%s\t%s\t%s\t%s\n' \
  "$SOURCE_URL" "jan76_dec20.ndk" "$size" "$sha256" \
  > "$DOWNLOAD_DIR/download_inventory.tsv"

echo "source_bytes=$size source_sha256=$sha256"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
