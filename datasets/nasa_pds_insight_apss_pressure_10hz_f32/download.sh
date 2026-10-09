#!/usr/bin/env bash
# Download the 28 pinned InSight APSS PS calibrated full-sol 10 Hz CSV
# products (ps_calib_<SOL>_<VV>.csv, PDS4 bundle urn:nasa:pds:insight_ps,
# data_calibrated collection) from the NASA PDS Atmospheres Node.
# Anonymous HTTPS only.  Resumable .part files, promoted only at the pinned
# byte size and the PDS4-label MD5 (files.tsv); every file is then fully
# parsed as a semantic check (header, 9 fields, label record count, 4-decimal
# PRESSURE, 10 Hz cadence, float32 round trip).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="nasa_pds_insight_apss_pressure_10hz_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
INVENTORY="$RECIPE_DIR/files.tsv"
PY="$RECIPE_DIR/scripts/apss_ps.py"
BASE_URL="https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/data_calibrated"
UA="openzl-public-datasets-insight-apss/1.0"
MAX_PASSES=8

mkdir -p "$DOWNLOAD_DIR/csv" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 "$RECIPE_DIR/scripts/selftest_apss.py"

# Liveness: one-byte range GET of the first pinned file must return 'A' (AOBT header).
first_dir="$(awk -F'\t' 'NR==2 {print $1}' "$INVENTORY")"
first="$(awk -F'\t' 'NR==2 {print $2}' "$INVENTORY")"
probe="$(curl --fail --silent --show-error --location --max-time 60 --retry 3 \
  --user-agent "$UA" --range 0-0 "$BASE_URL/$first_dir/$first")"
if [ "$probe" != "A" ]; then
  echo "FATAL: liveness probe did not return the CSV header byte (got '$probe')" >&2
  exit 1
fi
echo "liveness ok ($first)"

CONFIG="$DOWNLOAD_DIR/curl_csv.cfg"
for pass in $(seq 1 "$MAX_PASSES"); do
  python3 "$PY" plan --inventory "$INVENTORY" --downloads "$DOWNLOAD_DIR" --config "$CONFIG"
  pending="$(grep -c '^url = ' "$CONFIG" || true)"
  if [ "$pending" = "0" ]; then
    echo "all files complete after pass=$pass"
    break
  fi
  echo "[$(date -Is)] pass=$pass fetching=$pending"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
    --continue-at - --parallel --parallel-max 3 \
    --user-agent "$UA" --config "$CONFIG" || echo "curl reported failures on pass=$pass; revalidating"
done
python3 "$PY" plan --inventory "$INVENTORY" --downloads "$DOWNLOAD_DIR" --config "$CONFIG"
if [ "$(grep -c '^url = ' "$CONFIG" || true)" != "0" ]; then
  echo "FATAL: downloads still incomplete after $MAX_PASSES passes" >&2
  exit 1
fi
rm -f "$CONFIG"

python3 "$PY" check-downloads --inventory "$INVENTORY" --downloads "$DOWNLOAD_DIR"
echo "total_bytes=$(du -sb "$DOWNLOAD_DIR/csv" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
