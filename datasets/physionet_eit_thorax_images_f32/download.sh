#!/usr/bin/env bash
# Fetch the pinned PhysioNet "Respiratory and heart rate monitoring dataset
# from aeration study" 1.0.0 release files needed for the EIT image recipe:
# SHA256SUMS.txt, LICENSE.txt, README.txt, Code/read_binData.m and all 20
# forced-expiratory-manoeuvre EIT exports EIT_rawData/S01..S20_FEM.bin from the
# anonymous PhysioNet open-data S3 bucket. Every file is checked against the
# pinned SHA-256 (and the release SHA256SUMS.txt); EIT files are additionally
# checked for the 4358-byte frame structure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="physionet_eit_thorax_images_f32"
VERSION="1.0.0"
BASE_URL="https://physionet-open.s3.amazonaws.com/respiratory-heartrate-dataset/$VERSION"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-physionet-eit/1.0"
MAX_ATTEMPTS="${EIT_MAX_ATTEMPTS:-4}"

# Pinned release-level files (sha256 of the bytes served for 1.0.0).
SUMS_SHA256="e463d8351c734df9d286d26cfb64d82ac56684678449ad42ba570fea84296011"
LICENSE_SHA256="9a78e7f22742dde9f66ae235ec793ba2212019dc4d0ced75c4da09ced0b35fb2"
README_SHA256="4ea31ef7082e86918a793796327c890730437a94747b8db90dad0ba3f185dc70"
READER_SHA256="cc09fef3ce2a7a0e2bb62f9ece90418db2992b790b178d7c731f16e191fa60fc"

mkdir -p "$DOWNLOAD_DIR/EIT_rawData" "$DOWNLOAD_DIR/Code" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID version=$VERSION base=$BASE_URL"

sha_ok() {
  printf '%s  %s\n' "$1" "$2" | sha256sum --check --status
}

fetch_small() {
  local rel="$1" expected="$2" max_bytes="$3"
  local out="$DOWNLOAD_DIR/$rel"
  if [ -s "$out" ] && sha_ok "$expected" "$out"; then
    echo "cache_hit file=$rel"
    return
  fi
  rm -f "$out" "$out.part"
  echo "fetch file=$rel"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
    --speed-limit 1024 --speed-time 120 --max-filesize "$max_bytes" \
    --user-agent "$UA" --output "$out.part" "$BASE_URL/$rel"
  if ! sha_ok "$expected" "$out.part"; then
    echo "FATAL: sha256 mismatch for $rel (release changed or transfer corrupted)" >&2
    rm -f "$out.part"
    exit 1
  fi
  mv "$out.part" "$out"
}

fetch_small "SHA256SUMS.txt" "$SUMS_SHA256" 1000000
fetch_small "LICENSE.txt" "$LICENSE_SHA256" 200000
fetch_small "README.txt" "$README_SHA256" 200000
fetch_small "Code/read_binData.m" "$READER_SHA256" 200000

SUMS="$DOWNLOAD_DIR/SHA256SUMS.txt"
grep -qx "$LICENSE_SHA256 LICENSE.txt" "$SUMS" || { echo "FATAL: SHA256SUMS.txt does not list the pinned LICENSE.txt" >&2; exit 1; }
grep -qx "$README_SHA256 README.txt" "$SUMS" || { echo "FATAL: SHA256SUMS.txt does not list the pinned README.txt" >&2; exit 1; }
grep -qx "$READER_SHA256 Code/read_binData.m" "$SUMS" || { echo "FATAL: SHA256SUMS.txt does not list the pinned read_binData.m" >&2; exit 1; }
head -n 1 "$DOWNLOAD_DIR/LICENSE.txt" | tr -d '\r' | grep -qx "Creative Commons Attribution 4.0 International Public License" \
  || { echo "FATAL: LICENSE.txt is not the CC BY 4.0 legal code" >&2; exit 1; }
grep -q "4358" "$DOWNLOAD_DIR/Code/read_binData.m" && grep -q "\[1 1024\],'float32'" "$DOWNLOAD_DIR/Code/read_binData.m" \
  || { echo "FATAL: read_binData.m no longer documents the 4358-byte / 1024-float32 frame layout" >&2; exit 1; }
echo "release_files_ok license=CC-BY-4.0"

mapfile -t RESOURCES < <(python3 "$RECIPE_DIR/scripts/eit_bin.py" resources)
[ "${#RESOURCES[@]}" = "20" ] || { echo "FATAL: expected 20 pinned FEM recordings, got ${#RESOURCES[@]}" >&2; exit 1; }
for line in "${RESOURCES[@]}"; do
  read -r name size sha <<< "$line"
  grep -qx "$sha EIT_rawData/$name" "$SUMS" || { echo "FATAL: SHA256SUMS.txt does not vouch for pinned $name" >&2; exit 1; }
  [ $((size % 4358)) = 0 ] || { echo "FATAL: pinned size of $name is not a multiple of 4358" >&2; exit 1; }
done
echo "pinned_scope_ok recordings=${#RESOURCES[@]}"

# Liveness: one-byte range GET on the first recording.
first_name="$(printf '%s\n' "${RESOURCES[0]}" | cut -d' ' -f1)"
code="$(curl --silent --location --range 0-0 --max-time 60 --user-agent "$UA" \
  --output /dev/null --write-out '%{http_code}' "$BASE_URL/EIT_rawData/$first_name" || true)"
echo "liveness url=$BASE_URL/EIT_rawData/$first_name http=$code"
case "$code" in 200|206) ;; *) echo "FATAL: liveness check failed (http=$code)" >&2; exit 1 ;; esac

fetched_bytes=0
for line in "${RESOURCES[@]}"; do
  read -r name size sha <<< "$line"
  out="$DOWNLOAD_DIR/EIT_rawData/$name"
  part="$out.part"
  if [ -f "$out" ] && [ "$(stat -c %s "$out")" = "$size" ] && sha_ok "$sha" "$out"; then
    echo "cache_hit file=EIT_rawData/$name bytes=$size"
    continue
  fi
  rm -f "$out"
  attempt=0
  while :; do
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: EIT_rawData/$name not obtained after $MAX_ATTEMPTS attempts" >&2
      exit 1
    fi
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    if [ "$have" -gt "$size" ]; then
      echo "discard oversized partial file=$name have=$have expected=$size"
      rm -f "$part"
      have=0
    fi
    if [ "$have" -lt "$size" ]; then
      echo "[$(date -Is)] fetch file=EIT_rawData/$name attempt=$attempt resume_from=$have expected=$size"
      rc=0
      curl --fail --silent --show-error --location --continue-at - \
        --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
        --speed-limit 1024 --speed-time 120 --max-filesize "$((size + 1))" \
        --user-agent "$UA" --output "$part" "$BASE_URL/EIT_rawData/$name" || rc=$?
      if [ "$rc" != "0" ]; then
        echo "curl_exit=$rc file=$name attempt=$attempt (will resume)"
        sleep 5
        continue
      fi
    fi
    have="$(stat -c %s "$part")"
    if [ "$have" != "$size" ]; then
      echo "size_mismatch file=$name have=$have expected=$size (will resume)"
      continue
    fi
    if ! sha_ok "$sha" "$part"; then
      echo "sha256_mismatch file=$name attempt=$attempt; discarding partial file"
      rm -f "$part"
      continue
    fi
    mv "$part" "$out"
    fetched_bytes=$((fetched_bytes + size))
    echo "fetched file=EIT_rawData/$name bytes=$size sha256=$sha"
    break
  done
done
echo "fetched_bytes_this_run=$fetched_bytes"

python3 "$RECIPE_DIR/scripts/eit_bin.py" check-downloads --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
