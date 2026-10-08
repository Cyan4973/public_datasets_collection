#!/usr/bin/env bash
# Build the M3D IWR6843AOP raw-ADC samples from local files only: re-check each
# pinned capture's conf_file.cfg (exact profile, 100 ms frames) and DCA1000 log,
# stream-inflate the downloaded ZIP member range, check CRC-32 and every
# 64-byte HSI chirp header, drop the headers and write the 1024-byte int16
# payloads of all chirps, in stored order, as one little-endian sample per
# capture file. Writes the sample index and ingest stats.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_m3d_iwr6843_radar_adc_i16"
DL="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

for d in "$DL/meta" "$DL/ranges"; do
  [ -d "$d" ] || { echo "FATAL: missing $d; run download.sh first" >&2; exit 1; }
done

python3 "$RECIPE_DIR/scripts/m3d_tool.py" build \
  --selection "$RECIPE_DIR/selection.tsv" \
  --meta-dir "$DL/meta" \
  --ranges-dir "$DL/ranges" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --data-root "$DATA_ROOT"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
