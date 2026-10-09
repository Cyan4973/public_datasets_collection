#!/usr/bin/env bash
# Download the 24 pinned Cloudnet "lidar" product files (Lindenberg, DWD Lufft
# CHM15k serial CHM100110, instrument cdf99c53-6bd0-4146-be2a-604cf1164c30;
# the 1st and 15th of every month of 2024) listed in sources.tsv.
#
# 1. One small files-API request per pinned uuid (GET /api/files/<uuid>):
#    filename, date, size, sha256, instrument, site, product, errorLevel
#    "pass", coverage >= 0.99, cloudnetpy version and downloadUrl must equal
#    the pin.  This doubles as the liveness check: the download endpoint
#    ignores HTTP Range (a range GET returns the whole file with status 200),
#    so no range probes and no curl -C - resume are used.
# 2. Each file is fetched whole into a fresh .part file, then accepted only if
#    its size and SHA-256 match the pin and it decodes to the expected beta_raw
#    matrix (scripts/chm15k.py check-file); otherwise it is discarded and
#    re-fetched (up to MAX_TRIES times).  Existing verified files are kept.
# Anonymous HTTPS only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="cloudnet_lindenberg_chm15k_beta_raw_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
API="https://cloudnet.fmi.fi/api"
SOURCES="$RECIPE_DIR/sources.tsv"
PY="$RECIPE_DIR/scripts/chm15k.py"
MAX_TRIES=4
UA="openzl-public-datasets-cloudnet/1.0"

mkdir -p "$DOWNLOAD_DIR/nc" "$DOWNLOAD_DIR/meta" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

export PYTHONDONTWRITEBYTECODE=1
python3 -I "$PY" selftest

# 1. Per-file API records (about 3 KB each), re-fetched every run.
tail -n +2 "$SOURCES" | while IFS=$'\t' read -r day uuid _filename _size _sha _version; do
  meta="$DOWNLOAD_DIR/meta/${day//-/}.json"
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 5 --retry-all-errors --max-time 120 \
    --user-agent "$UA" --output "$meta.part" "$API/files/$uuid"
  mv "$meta.part" "$meta"
  python3 -I "$PY" check-meta --sources "$SOURCES" --meta "$meta"
done

# 2. Whole-file fetches with size + sha256 + decode validation.
tail -n +2 "$SOURCES" | while IFS=$'\t' read -r day uuid filename size sha _version; do
  out="$DOWNLOAD_DIR/nc/$filename"
  if [ -f "$out" ]; then
    if python3 -I "$PY" check-file --sources "$SOURCES" --date "$day" --file "$out"; then
      echo "present $day"
      continue
    fi
    echo "discarding invalid local copy of $day"
    rm -f "$out"
  fi
  ok=0
  for try in $(seq 1 "$MAX_TRIES"); do
    rm -f "$out.part"
    echo "[$(date -Is)] fetch $day try=$try size=$size"
    if curl --fail --silent --show-error --location \
        --retry 3 --retry-delay 10 --retry-all-errors \
        --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
        --user-agent "$UA" --output "$out.part" \
        "$API/download/product/$uuid/$filename"; then
      if python3 -I "$PY" check-file --sources "$SOURCES" --date "$day" --file "$out.part"; then
        mv "$out.part" "$out"
        ok=1
        break
      fi
    fi
    echo "attempt $try for $day failed; retrying"
    sleep 10
  done
  rm -f "$out.part"
  if [ "$ok" != "1" ]; then
    echo "FATAL: could not obtain a valid copy of $day after $MAX_TRIES tries" >&2
    exit 1
  fi
done

count="$(find "$DOWNLOAD_DIR/nc" -maxdepth 1 -name '*.nc' | wc -l)"
if [ "$count" != "24" ]; then
  echo "FATAL: expected 24 files, found $count" >&2
  exit 1
fi
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$count bytes=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
