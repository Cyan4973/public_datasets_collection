#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="tum_rgbd_depth_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# TUM RGB-D benchmark sequences are distributed as per-sequence .tgz archives
# containing a depth/ folder of 16-bit grayscale PNG depth frames (640x480,
# scale factor 5000: metres = pixel/5000). One depth frame is one natural sample.
# We download a bounded set of sequences (default one) and the build extracts a
# capped number of depth frames. Only depth is used; the archive also carries rgb.
TUM_SEQUENCES="${TUM_SEQUENCES:-freiburg1_xyz}"
MAX_FILE_BYTES="${MAX_FILE_BYTES:-3000000000}"   # 3 GB guard per archive
TUM_TGZ_URLS="${TUM_TGZ_URLS:-}"                 # optional explicit URL list (overrides)
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
HOSTS=("https://cvg.cit.tum.de" "https://vision.in.tum.de")

is_gzip() { [ "$(LC_ALL=C head -c 2 "$1" | od -An -tx1 | tr -d ' \n')" = "1f8b" ]; }

# Resolve (local_name, url-candidates) list into a plan we then fetch.
declare -a NAMES=() URLS=()
if [ -n "$TUM_TGZ_URLS" ]; then
  for url in $TUM_TGZ_URLS; do
    NAMES+=("$(basename "${url%%\?*}")"); URLS+=("$url")
  done
else
  for seq in $TUM_SEQUENCES; do
    digit="$(printf '%s' "$seq" | sed -nE 's/^freiburg([0-9]).*/\1/p')"
    [ -n "$digit" ] || { echo "  WARN: cannot derive group from sequence '$seq'"; continue; }
    file="rgbd_dataset_${seq}.tgz"
    for host in "${HOSTS[@]}"; do
      NAMES+=("$file"); URLS+=("$host/rgbd/dataset/freiburg${digit}/$file")
    done
  done
fi

ok=0
declare -A done_name=()
for i in "${!URLS[@]}"; do
  name="${NAMES[$i]}"; url="${URLS[$i]}"
  [ -n "${done_name[$name]:-}" ] && continue   # already fetched this archive from another host
  out="$DOWNLOAD_DIR/$name"; part="$out.part"

  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && is_gzip "$out"; then
    echo "cache_hit name=$name bytes=$(wc -c < "$out" | tr -d ' ')"
    done_name[$name]=1; ok=$((ok+1)); continue
  fi

  echo "try url=$url"
  rm -f "$part"
  if ! curl --globoff -fSL --retry 10 --retry-delay 5 \
        --speed-limit 1024 --speed-time 120 --max-filesize "$MAX_FILE_BYTES" \
        -C - -A "$UA" -o "$part" "$url"; then
    echo "  WARN: fetch failed"; rm -f "$part"; continue
  fi
  if ! is_gzip "$part"; then
    echo "  WARN: not a gzip archive"; rm -f "$part"; continue
  fi
  mv "$part" "$out"
  echo "downloaded name=$name bytes=$(wc -c < "$out" | tr -d ' ')"
  done_name[$name]=1; ok=$((ok+1))
done

echo "usable_archives=$ok"
if [ "$ok" -lt 1 ]; then
  echo "FATAL: no TUM RGB-D archives downloaded."
  echo "       Set TUM_SEQUENCES='freiburg1_xyz freiburg2_desk' or TUM_TGZ_URLS='<url> ...'."
  exit 1
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID archives=$ok"
