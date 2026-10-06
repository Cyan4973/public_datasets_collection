#!/usr/bin/env bash
# Fetch the pinned GRABMyo 1.1.0 Session 1 / trial 1 WFDB records (731
# .dat/.hea pairs: 43 participants x 17 gestures) from the anonymous PhysioNet
# open-data S3 bucket, check every file against the release SHA256SUMS.txt,
# and validate WFDB header semantics and per-signal checksums.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="physionet_grabmyo_semg_i16"
VERSION="1.1.0"
BASE_URL="${GRABMYO_BASE_URL:-https://physionet-open.s3.amazonaws.com/grabmyo/$VERSION}"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-grabmyo-semg/1.0"
MAX_PASSES="${GRABMYO_MAX_PASSES:-6}"

# Pinned identities of the release-level files served for 1.1.0.
SUMS_SHA256="757ea64fa5134b7b3b84d9f79e30cfa1ac4d2c65a40ce9b427db11dd8258974e"     # 4,300,947 B
LICENSE_SHA256="9a78e7f22742dde9f66ae235ec793ba2212019dc4d0ced75c4da09ced0b35fb2"  # 14,842 B
README_SHA256="1db9b7889c0868a35f6067ecb109f716cb88cd1a9549c39f4edecb1c33dfca05"   # 2,448 B
MOTION_SHA256="10e2919838e85e4837fd63ec096deae1a7353ecf53ac033093d64b551018067e"   # 630 B

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID version=$VERSION base=$BASE_URL"

fetch_small() {
  local name="$1" expected="$2" max_bytes="$3"
  local out="$DOWNLOAD_DIR/$name"
  if [ -s "$out" ] && printf '%s  %s\n' "$expected" "$out" | sha256sum --check --status; then
    echo "cache_hit file=$name"
    return
  fi
  rm -f "$out" "$out.part"
  echo "fetch file=$name"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
    --speed-limit 1024 --speed-time 120 --max-filesize "$max_bytes" \
    --user-agent "$UA" --output "$out.part" "$BASE_URL/$name"
  if ! printf '%s  %s\n' "$expected" "$out.part" | sha256sum --check --status; then
    echo "FATAL: sha256 mismatch for $name (release changed or transfer corrupted)" >&2
    rm -f "$out.part"
    exit 1
  fi
  mv "$out.part" "$out"
}

fetch_small "SHA256SUMS.txt" "$SUMS_SHA256" 10000000
fetch_small "LICENSE.txt" "$LICENSE_SHA256" 200000
fetch_small "readme.txt" "$README_SHA256" 200000
fetch_small "MotionSequence.txt" "$MOTION_SHA256" 200000

# The pinned checksum list must itself vouch for the release files, and the
# license must be the CC BY 4.0 legal code.
for pair in "$LICENSE_SHA256 LICENSE.txt" "$README_SHA256 readme.txt" "$MOTION_SHA256 MotionSequence.txt"; do
  grep -qx "$pair" "$DOWNLOAD_DIR/SHA256SUMS.txt" || { echo "FATAL: SHA256SUMS.txt does not list '$pair'" >&2; exit 1; }
done
head -n 1 "$DOWNLOAD_DIR/LICENSE.txt" | tr -d '\r' | grep -qx "Creative Commons Attribution 4.0 International Public License" \
  || { echo "FATAL: LICENSE.txt is not the CC BY 4.0 legal code" >&2; exit 1; }
echo "release_files_ok license=CC-BY-4.0"

# 1,462 small objects (731 x 655,360 B .dat + 731 x ~3.1 KB .hea). Each pass
# promotes verified .part files, deletes corrupt ones, and fetches what is
# still missing in one parallel curl run with retries. No per-file
# --max-time; stalls are caught by --speed-limit/--speed-time.
PARALLEL_FLAGS=()
if curl --help all 2>/dev/null | grep -q -- "--parallel-max"; then
  PARALLEL_FLAGS=(--parallel --parallel-max 8)
fi
CFG="$DOWNLOAD_DIR/.curl_batch.cfg"
PENDING_FILE="$DOWNLOAD_DIR/.pending_count"
pass=0
while :; do
  python3 "$RECIPE_DIR/scripts/grabmyo_recipe.py" plan \
    --download-dir "$DOWNLOAD_DIR" --base-url "$BASE_URL" --config "$CFG" --pending-out "$PENDING_FILE"
  pending="$(cat "$PENDING_FILE")"
  if [ "$pending" = "0" ]; then
    break
  fi
  pass=$((pass + 1))
  if [ "$pass" -gt "$MAX_PASSES" ]; then
    echo "FATAL: $pending files still missing or invalid after $MAX_PASSES passes" >&2
    exit 1
  fi
  echo "[$(date -Is)] fetch pass=$pass files=$pending"
  rc=0
  curl ${PARALLEL_FLAGS[@]+"${PARALLEL_FLAGS[@]}"} --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
    --speed-limit 1024 --speed-time 120 --max-filesize 1000000 \
    --user-agent "$UA" --config "$CFG" || rc=$?
  echo "[$(date -Is)] fetch pass=$pass curl_exit=$rc"
done
rm -f "$CFG" "$PENDING_FILE"

python3 "$RECIPE_DIR/scripts/grabmyo_recipe.py" check-downloads --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
