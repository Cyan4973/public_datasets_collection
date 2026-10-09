#!/usr/bin/env bash
# Documentation only: regenerate pinned_series.tsv. download.sh never runs
# this. Discovery output goes to $DATA_DIR/discovery/<id>/; compare it with
# the committed pin file. Makes 14 small getSOPInstanceUIDs calls and reads
# the first 1 MiB of 14 getSingleImage streams (no Range header) to pin the
# DICOM headers.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tcia_remind_intraop_brain_ultrasound_u8"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DISCOVERY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1

listing="$DISCOVERY_DIR/series_us.json"
if [ ! -s "$listing" ]; then
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
    --max-time 300 --max-filesize 20000000 --output "$listing.part" \
    "https://services.cancerimagingarchive.net/nbia-api/services/v1/getSeries?Collection=ReMIND&Modality=US"
  mv "$listing.part" "$listing"
fi
python3 "$RECIPE_DIR/discover.py" --listing "$listing" --out "$DISCOVERY_DIR/pinned_series.tsv"
if cmp -s "$DISCOVERY_DIR/pinned_series.tsv" "$RECIPE_DIR/pinned_series.tsv"; then
  echo "discovery reproduces the committed pin file"
else
  echo "discovery differs from the committed pin file" >&2
  exit 1
fi
