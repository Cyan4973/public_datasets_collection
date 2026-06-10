#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=ourworldindata_co2_latest
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
URL="https://ourworldindata.org/grapher/annual-co2-emissions-per-country.csv"
OUT="$DOWNLOAD_DIR/annual-co2-emissions-per-country.csv"
TMP="$OUT.tmp"
if [[ "$FORCE_DOWNLOAD" != "1" && -s "$OUT" ]]; then
  echo "cache_hit key=ourworldindata_co2_latest path=$OUT"
  cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
  exit 0
fi
echo "fetch key=ourworldindata_co2_latest url=$URL"
rm -f "$TMP"
if ! curl --globoff --fail --location --retry 3 --retry-delay 2 --silent --show-error "$URL" -o "$TMP"; then
  echo -e "ourworldindata_co2_latest\t$URL\tcurl_failed" >> "$FAILURES"
  rm -f "$TMP"
  cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
  exit 1
fi
if ! grep -Eq "^Entity,Code,Year," "$TMP"; then
  echo -e "ourworldindata_co2_latest\t$URL\tvalidation_failed" >> "$FAILURES"
  rm -f "$TMP"
  cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
  exit 1
fi
mv "$TMP" "$OUT"
echo "fetch_ok key=ourworldindata_co2_latest bytes=$(stat -c '%s' "$OUT")"
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
