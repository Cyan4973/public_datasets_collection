#!/usr/bin/env bash
# Fetch the pinned PhysioNet CirCor DigiScope 1.0.3 recordings (all 3,163
# WAV + WFDB header pairs) from the PhysioNet open-data S3 bucket, check every
# file against the official SHA256SUMS.txt, and validate WAV/header semantics.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="physionet_circor_pcg_i16"
VERSION="1.0.3"
BASE_URL="${CIRCOR_BASE_URL:-https://physionet-open.s3.amazonaws.com/circor-heart-sound/$VERSION}"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-circor-pcg/1.0"
MAX_PASSES="${CIRCOR_MAX_PASSES:-6}"

# Pinned identities of the release-level files (sha256 of the bytes served for 1.0.3).
SUMS_SHA256="9724d3f0fc2fb65edfa29fe22ea7a9f3aceda96d5fd94b649ff8e52b53b2e50c"
LICENSE_SHA256="86c0ad300f6d380591298bc03652e30b81f65954bbf22435812bcfd46812ab06"
RECORDS_SHA256="953b0da03a23abb43aba4151088f6dbe97b8805a61f1622c01dc929f14fd167d"

mkdir -p "$DOWNLOAD_DIR/training_data" "$LOG_DIR"
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

fetch_small "SHA256SUMS.txt" "$SUMS_SHA256" 2000000
fetch_small "LICENSE.txt" "$LICENSE_SHA256" 200000
fetch_small "RECORDS" "$RECORDS_SHA256" 200000

# The pinned checksum list must itself vouch for LICENSE.txt and RECORDS, and
# the license must be the ODC Attribution License text.
grep -qx "$LICENSE_SHA256 LICENSE.txt" "$DOWNLOAD_DIR/SHA256SUMS.txt" || { echo "FATAL: SHA256SUMS.txt does not list the pinned LICENSE.txt" >&2; exit 1; }
grep -qx "$RECORDS_SHA256 RECORDS" "$DOWNLOAD_DIR/SHA256SUMS.txt" || { echo "FATAL: SHA256SUMS.txt does not list the pinned RECORDS" >&2; exit 1; }
head -n 1 "$DOWNLOAD_DIR/LICENSE.txt" | grep -q "ODC Attribution License (ODC-By)" || { echo "FATAL: LICENSE.txt is not the ODC-By text" >&2; exit 1; }
echo "release_files_ok license=ODC-By-1.0"

# Thousands of small objects: each pass promotes verified .part files, deletes
# corrupt ones, and fetches what is still missing in one parallel curl run with
# retries. No per-file --max-time; stalls are caught by --speed-limit/--speed-time.
PARALLEL_FLAGS=()
if curl --help all 2>/dev/null | grep -q -- "--parallel-max"; then
  PARALLEL_FLAGS=(--parallel --parallel-max 8)
fi
CFG="$DOWNLOAD_DIR/.curl_batch.cfg"
PENDING_FILE="$DOWNLOAD_DIR/.pending_count"
pass=0
while :; do
  python3 "$RECIPE_DIR/scripts/circor_pcg.py" plan \
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
    --speed-limit 1024 --speed-time 120 --max-filesize 2000000 \
    --user-agent "$UA" --config "$CFG" || rc=$?
  echo "[$(date -Is)] fetch pass=$pass curl_exit=$rc"
done
rm -f "$CFG" "$PENDING_FILE"

python3 "$RECIPE_DIR/scripts/circor_pcg.py" check-downloads --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
