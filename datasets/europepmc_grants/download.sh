#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=europepmc_grants
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
URL="https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=GRANT_ID:*&format=json&pageSize=500"
OUT="$DOWNLOAD_DIR/europepmc_grants.json"
TMP="$OUT.tmp"
if [[ "$FORCE_DOWNLOAD" != "1" && -s "$OUT" ]]; then
  echo "cache_hit key=europepmc_grants path=$OUT"
  cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
  exit 0
fi
echo "fetch key=europepmc_grants url=$URL"
rm -f "$TMP"
if ! curl --globoff --fail --location --retry 3 --retry-delay 2 --silent --show-error "$URL" -o "$TMP"; then
  echo -e "europepmc_grants\t$URL\tcurl_failed" >> "$FAILURES"
  rm -f "$TMP"
  cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
  exit 1
fi
if ! jq -e ".resultList.result != null" "$TMP" >/dev/null 2>&1; then
  echo -e "europepmc_grants\t$URL\tvalidation_failed" >> "$FAILURES"
  rm -f "$TMP"
  cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
  exit 1
fi
mv "$TMP" "$OUT"
echo "fetch_ok key=europepmc_grants bytes=$(stat -c '%s' "$OUT")"
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
