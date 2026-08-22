#!/usr/bin/env bash
# Acquire and preflight the versioned English Asterisk Core Sounds mu-law release.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="asterisk_core_sounds_ulaw_u8"
RECIPE_DIR="$REPO_ROOT/datasets/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
ARCHIVE="$DOWNLOAD_DIR/asterisk-core-sounds-en-ulaw-1.6.1.tar.gz"
URL="https://downloads.asterisk.org/pub/telephony/sounds/releases/asterisk-core-sounds-en-ulaw-1.6.1.tar.gz"

mkdir -p "$DOWNLOAD_DIR" "$DISCOVERY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

if [[ ! -f "$ARCHIVE" || "${FORCE_DOWNLOAD:-0}" == "1" ]]; then
  PART="$ARCHIVE.part"
  rm -f "$PART"
  curl --globoff --fail-with-body --silent --show-error --location \
    --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 \
    --max-time 1800 --max-filesize 100000000 \
    --user-agent "openzl-public-datasets/1.0" --output "$PART" "$URL"
  [[ -s "$PART" ]] || { echo "empty response for $URL" >&2; exit 1; }
  mv "$PART" "$ARCHIVE"
else
  echo "reuse existing $(basename "$ARCHIVE") bytes=$(stat -c %s "$ARCHIVE")"
fi

python3 "$RECIPE_DIR/scripts/asterisk_ulaw.py" preflight \
  --archive "$ARCHIVE" --profile "$DISCOVERY_DIR/source_profile.json"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
