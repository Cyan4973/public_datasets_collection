#!/usr/bin/env bash
# Documentation only: regenerate pinned_series.tsv. download.sh never runs this
# and never re-pulls the ~9.9 MB CR listing. Discovery output goes to
# $DATA_DIR/discovery/<id>/; compare it with the committed pin file.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="tcia_covid19_ny_sbu_chest_cr_u16"
DISCOVERY_DIR="$REPO_ROOT/$DATA_DIR/discovery/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DISCOVERY_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1

listing="$DISCOVERY_DIR/series_cr.json"
if [ ! -s "$listing" ]; then
  curl --fail --silent --show-error --location --retry 5 --retry-delay 3 \
    --max-time 600 --max-filesize 50000000 --output "$listing.part" \
    "https://services.cancerimagingarchive.net/nbia-api/services/v1/getSeries?Collection=COVID-19-NY-SBU&Modality=CR"
  mv "$listing.part" "$listing"
fi
python3 "$RECIPE_DIR/discover.py" --listing "$listing" --out "$DISCOVERY_DIR/pinned_series.tsv"
if cmp -s "$DISCOVERY_DIR/pinned_series.tsv" "$RECIPE_DIR/pinned_series.tsv"; then
  echo "discovery reproduces the committed pin file"
else
  echo "discovery differs from the committed pin file" >&2
  exit 1
fi
